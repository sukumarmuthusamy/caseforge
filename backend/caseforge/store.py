"""SQLite persistence: two tables, no ORM.

`events` is the source of truth. `runs` holds metadata that is deliberately
kept out of the hashed log: labels, lineage, wall-clock creation time, the
reveal flag, and the compatibility stamp and verdict (see `compat.py`).

Columns are only ever added. A database written by an earlier build is opened
as it is: the missing columns are added empty, which is how a legacy run is
recognised, and no row or event is rewritten.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id               TEXT PRIMARY KEY,
    scenario_id      TEXT NOT NULL,
    scenario_version TEXT NOT NULL,
    scenario_hash    TEXT NOT NULL,
    seed             INTEGER NOT NULL,
    label            TEXT NOT NULL DEFAULT '',
    parent_run_id    TEXT,
    fork_tick        INTEGER,
    fork_seq         INTEGER,
    revealed         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    rules_version    TEXT,
    fingerprint      TEXT,
    verified_fingerprint TEXT,
    verified_events  INTEGER,
    verdict          TEXT,
    divergence       INTEGER,
    verdict_detail   TEXT
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT    NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq    INTEGER NOT NULL,
    tick   INTEGER NOT NULL,
    type   TEXT    NOT NULL,
    actor  TEXT    NOT NULL,
    cause  INTEGER,
    data   TEXT    NOT NULL,
    hash   TEXT    NOT NULL,
    PRIMARY KEY (run_id, seq)
);
"""


# Columns added after the first release of the schema, as (name, type).
ADDED_COLUMNS = (
    ("rules_version", "TEXT"),
    ("fingerprint", "TEXT"),
    ("verified_fingerprint", "TEXT"),
    ("verified_events", "INTEGER"),
    ("verdict", "TEXT"),
    ("divergence", "INTEGER"),
    ("verdict_detail", "TEXT"),
)


class StoreError(Exception):
    pass


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.executescript(SCHEMA)
            present = {row["name"] for row in conn.execute("PRAGMA table_info(runs)")}
            for name, kind in ADDED_COLUMNS:
                if name not in present:
                    conn.execute(f"ALTER TABLE runs ADD COLUMN {name} {kind}")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _insert_events(conn: sqlite3.Connection, run_id: str, events: list[Event]) -> None:
        conn.executemany(
            "INSERT INTO events (run_id, seq, tick, type, actor, cause, data, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (run_id, e.seq, e.tick, e.type, e.actor, e.cause, json.dumps(e.data, sort_keys=True, separators=(",", ":")), e.hash)
                for e in events
            ],
        )

    def create_run(
        self,
        run_id: str,
        scenario_id: str,
        scenario_version: str,
        scenario_hash: str,
        seed: int,
        events: list[Event],
        label: str = "",
        parent_run_id: str | None = None,
        fork_tick: int | None = None,
        stamp: dict[str, str] | None = None,
    ) -> None:
        """`stamp` is {rules_version, fingerprint} of the behaviour the events came from.
        The events are also recorded as verified under the build that is writing them."""
        from .compat import behaviour_fingerprint

        stamp = stamp or {}
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        fork_seq = events[-1].seq if parent_run_id and events else None
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT INTO runs (id, scenario_id, scenario_version, scenario_hash, seed, label, parent_run_id, fork_tick, fork_seq, created_at,"
                " rules_version, fingerprint, verified_fingerprint, verified_events, verdict, verdict_detail)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok', 'written by this build')",
                (run_id, scenario_id, scenario_version, scenario_hash, seed, label, parent_run_id, fork_tick, fork_seq, created,
                 stamp.get("rules_version"), stamp.get("fingerprint"), behaviour_fingerprint(), len(events)),
            )
            self._insert_events(conn, run_id, events)

    def append_events(self, run_id: str, events: list[Event], verified: tuple[str, int] | None = None) -> None:
        """Append in one transaction. Refuses gaps; the primary key refuses duplicates.

        `verified` is (fingerprint, event count after the append): when given, the run's compatibility
        coverage is extended to that count in the same transaction, so the events and the coverage that
        describes them are written together or not at all. The extension applies only to a
        run whose stored verdict is `ok` under that fingerprint; for any other run it matches no row,
        which is correct (such a run is simply replayed on its next load), not an error.
        Any database error is reported as `StoreError` and leaves nothing written.
        """
        if not events:
            return
        try:
            with closing(self._connect()) as conn, conn:
                row = conn.execute("SELECT COALESCE(MAX(seq), -1) AS last FROM events WHERE run_id = ?", (run_id,)).fetchone()
                if events[0].seq != row["last"] + 1:
                    raise StoreError(f"run {run_id}: expected next seq {row['last'] + 1}, got {events[0].seq}")
                self._insert_events(conn, run_id, events)
                if verified is not None:
                    fingerprint, count = verified
                    conn.execute(
                        "UPDATE runs SET verified_events = ? WHERE id = ? AND verified_fingerprint = ? AND verdict = 'ok'",
                        (count, run_id, fingerprint),
                    )
        except sqlite3.Error as exc:
            raise StoreError(f"run {run_id}: {exc}") from exc

    def load_events(self, run_id: str) -> list[Event]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT seq, tick, type, actor, cause, data, hash FROM events WHERE run_id = ? ORDER BY seq", (run_id,)
            ).fetchall()
        return [
            Event(seq=r["seq"], tick=r["tick"], type=r["type"], actor=r["actor"], cause=r["cause"], data=json.loads(r["data"]), hash=r["hash"])
            for r in rows
        ]

    _RUN_QUERY = """
        SELECT r.*,
               (SELECT MAX(seq)  FROM events e WHERE e.run_id = r.id) AS last_seq,
               (SELECT MAX(tick) FROM events e WHERE e.run_id = r.id) AS tick,
               (SELECT COUNT(*)  FROM events e WHERE e.run_id = r.id AND e.type = 'CaseClosed') AS closed,
               (SELECT hash FROM events e WHERE e.run_id = r.id ORDER BY seq DESC LIMIT 1) AS head_hash
        FROM runs r
    """

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as conn:
            row = conn.execute(self._RUN_QUERY + " WHERE r.id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(self._RUN_QUERY + " ORDER BY r.created_at DESC, r.rowid DESC").fetchall()
        return [dict(row) for row in rows]

    def set_verdict(self, run_id: str, fingerprint: str, events: int, verdict: str, divergence: int | None, detail: str) -> None:
        """Record what replaying the run under `fingerprint` found. Adds a verdict; touches no event."""
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE runs SET verified_fingerprint = ?, verified_events = ?, verdict = ?, divergence = ?, verdict_detail = ? WHERE id = ?",
                (fingerprint, events, verdict, divergence, detail, run_id),
            )

    def set_revealed(self, run_id: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE runs SET revealed = 1 WHERE id = ?", (run_id,))

    def set_label(self, run_id: str, label: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE runs SET label = ? WHERE id = ?", (label, run_id))

    def delete_run(self, run_id: str) -> None:
        with closing(self._connect()) as conn, conn:
            conn.execute("DELETE FROM events WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
