"""Whether a stored run may be continued by this build (compat.py, DECISIONS D25).

Runs "recorded under other rules" are made for real: the reasoner's constant for a
suspect's word about himself is changed while the run is played and stored, then
restored, and the database is opened by a new service as after a restart. Nothing
here edits an event; the stamp and verdict live beside the log, outside its hash chain.
"""

from __future__ import annotations

import sqlite3

import pytest
from .conftest import LocalClient as TestClient

from caseforge import compat, reasoning
from caseforge.api import create_app
from caseforge.compat import CHANGED, CURRENT, VERIFIED, ContinuationRefused
from caseforge.engine import IncompatibleRun, verify_chain
from caseforge.service import RunService
from caseforge.store import Store

from .test_replay import rehashed

SCENARIO = "quiet_substitution"
POLICIES = {"ibarra": "deceptive"}


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "runs.sqlite3")


def record_under_other_rules(db, monkeypatch, ticks=14, policies=POLICIES, weight=2, rules="2026.11-older"):
    """Play and store a run while the reasoner weighs a suspect's own word at `weight`, stamped as such."""
    with monkeypatch.context() as patch:
        patch.setattr(reasoning, "SELF_SERVING_TESTIMONY_WEIGHT", weight)
        patch.setattr(compat, "RULES_VERSION", rules)
        patch.setattr(compat, "_FINGERPRINT", "older-behaviour0")
        service = RunService(Store(db))
        run = service.create_run(SCENARIO, 7, policies)
        service.step(run["id"], ticks)
        return run["id"]


def reopen(db):
    """A restart: a new service, no memory of the last one."""
    return RunService(Store(db))


def row(db, run_id):
    return Store(db).get_run(run_id)


@pytest.fixture
def no_replay(monkeypatch):
    """Any replay after this point is a failure: the stored stamp or verdict has to be enough."""
    def boom(*args, **kwargs):
        raise AssertionError("the run was replayed although a stamp or stored verdict covered it")

    monkeypatch.setattr(compat, "replay_verdict", boom)


# -- 1. a new run carries what it needs --------------------------------------------------


def test_a_new_run_is_stamped_and_needs_no_replay_to_open(db, monkeypatch):
    service = RunService(Store(db))
    run = service.create_run(SCENARIO, 7)
    stored = row(db, run["id"])
    assert stored["rules_version"] == reasoning.RULES_VERSION == "2026.11-voices"
    assert stored["fingerprint"] == compat.behaviour_fingerprint() == stored["verified_fingerprint"]
    assert (stored["verdict"], stored["verified_events"]) == ("ok", len(Store(db).load_events(run["id"])))
    monkeypatch.setattr(compat, "replay_verdict", lambda *a, **k: pytest.fail("replayed"))
    service.step(run["id"], 3)
    reopened = reopen(db)
    summary = reopened.summary(run["id"])
    assert summary["continuable"] is True and summary["compatible"] is True
    assert summary["compatibility"]["state"] == CURRENT and summary["compatibility"]["legacy"] is False
    assert summary["compatibility"]["stamped_rules"] == "2026.11-voices"
    # What was appended is covered too, so the next restart still replays nothing.
    assert row(db, run["id"])["verified_events"] == len(Store(db).load_events(run["id"]))


def test_the_stamp_is_outside_the_hash_chain_so_no_head_hash_moves(db):
    """Putting it in RunStarted would have changed every new run's hash. Seed 7 of the bundled case is pinned in test_pinned_runs."""
    service = RunService(Store(db))
    run = service.create_run("missing_prototype", 7)
    service.step(run["id"], 100)
    events = Store(db).load_events(run["id"])
    assert verify_chain(events) is None
    assert "rules_version" not in events[0].data and "fingerprint" not in events[0].data
    assert set(events[0].data) == {"scenario_id", "scenario_version", "scenario_hash", "engine_version", "seed", "agents", "policies", "max_ticks"}


def test_the_fingerprint_follows_the_replay_sources_and_ignores_line_endings(monkeypatch):
    assert len(compat.behaviour_fingerprint()) == 16
    assert compat.source_fingerprint(("reasoning.py",)) != compat.source_fingerprint(("engine.py",))
    assert compat.source_fingerprint(compat.REPLAY_SOURCES) == compat.behaviour_fingerprint()
    # Policies are not in it: a policy that would decide differently does not make the recorded past untrue.
    assert not any(name.startswith("policies") for name in compat.REPLAY_SOURCES)


# -- 2. older runs that still replay ------------------------------------------------------------


def test_a_legacy_run_without_a_stamp_is_verified_once_and_stays_usable(db, monkeypatch):
    service = RunService(Store(db))
    run = service.create_run(SCENARIO, 7, POLICIES)
    service.step(run["id"], 10)
    with sqlite3.connect(db) as conn:  # what a database written before stamps looks like
        conn.execute("UPDATE runs SET rules_version = NULL, fingerprint = NULL, verified_fingerprint = NULL, verified_events = NULL, verdict = NULL, verdict_detail = NULL")
    before = Store(db).load_events(run["id"])

    first = reopen(db).summary(run["id"])
    assert first["compatibility"]["state"] == VERIFIED and first["compatibility"]["legacy"] is True
    assert first["continuable"] is True and "reproduces all" in first["compatibility"]["detail"]
    stored = row(db, run["id"])
    assert (stored["verdict"], stored["verified_fingerprint"], stored["verified_events"]) == ("ok", compat.behaviour_fingerprint(), len(before))
    assert stored["fingerprint"] is None  # a legacy run is not re-labelled as if it had been stamped

    monkeypatch.setattr(compat, "replay_verdict", lambda *a, **k: pytest.fail("replayed again"))
    again = reopen(db)
    again.step(run["id"], 4)  # continues
    assert again.summary(run["id"])["compatibility"]["state"] == VERIFIED
    assert Store(db).load_events(run["id"])[: len(before)] == before
    assert reopen(db).summary(run["id"])["continuable"] is True  # the extension was covered: still no replay


def test_a_run_stamped_by_other_behaviour_that_still_replays_is_verified_and_continuable(db, monkeypatch):
    run_id = record_under_other_rules(db, monkeypatch, weight=reasoning.SELF_SERVING_TESTIMONY_WEIGHT, ticks=8)
    summary = reopen(db).summary(run_id)
    assert summary["compatibility"]["state"] == VERIFIED and summary["compatibility"]["legacy"] is False
    assert summary["compatibility"]["stamped_rules"] == "2026.11-older" and summary["compatibility"]["stamped_fingerprint"] == "older-behaviour0"
    assert summary["continuable"] is True
    service = reopen(db)
    service.step(run_id, 2)
    assert service.verify(run_id)["decisions"]["ok"] is True


@pytest.mark.parametrize("scenario_id, policies", [("missing_prototype", {}), ("missing_prototype", {"reyes": "deceptive"}), (SCENARIO, {}), (SCENARIO, POLICIES)])
def test_documented_bundled_runs_are_never_locked_out(db, scenario_id, policies):
    """The 720 documented runs keep their head hashes (README, D23), so any legacy copy replays."""
    service = RunService(Store(db))
    run = service.create_run(scenario_id, 3, policies)
    service.step(run["id"], 100)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE runs SET fingerprint = NULL, rules_version = NULL, verified_fingerprint = NULL, verified_events = NULL, verdict = NULL")
    summary = reopen(db).summary(run["id"])
    assert summary["compatibility"]["state"] == VERIFIED and summary["status"] == "closed"


# -- 3. runs that earlier rules recorded and these would not reproduce --------------------------------------


def test_a_run_the_current_rules_would_not_have_recorded_stays_listed_and_readable_but_cannot_continue(db, monkeypatch):
    run_id = record_under_other_rules(db, monkeypatch)
    before = Store(db).load_events(run_id)
    service = reopen(db)

    listed = {r["id"]: r for r in service.list_runs()}[run_id]
    assert listed["compatible"] is True and listed["continuable"] is False
    compat_info = listed["compatibility"]
    assert compat_info["state"] == CHANGED and compat_info["first_divergence"] == 157
    assert "diverges at event 157 (BeliefsRevised)" in compat_info["detail"] and "read-only" in compat_info["detail"]
    assert compat_info["stamped_rules"] == "2026.11-older" and compat_info["current_rules"] == "2026.11-voices"

    # Everything that only reads still works, and what it shows is what was recorded.
    snapshot = service.snapshot(run_id)
    assert snapshot["run"]["continuable"] is False and snapshot["latest_tick"] == 14
    assert service.snapshot(run_id, 5)["tick"] == 5
    assert service.graph(run_id, 5)["nodes"]
    assert [e["seq"] for e in service.events(run_id)] == [e.seq for e in before]
    assert service.evaluation(run_id)["progress"]
    report = service.verify(run_id)
    assert report["chain"]["ok"] is True and report["fold"]["ok"] is True
    assert report["decisions"]["ok"] is False and report["decisions"]["first_divergence"] == 157
    assert report["compatibility"]["state"] == CHANGED

    # Everything that would add to it is refused, and refuses without touching the log.
    for operation in (
        lambda: service.step(run_id, 1),
        lambda: service.intervene(run_id, "rumor_registrar"),
        lambda: service.set_policy(run_id, "hale", "hasty"),
    ):
        with pytest.raises(ContinuationRefused, match="read-only"):
            operation()
    assert Store(db).load_events(run_id) == before
    assert reopen(db).summary(run_id)["continuable"] is False


def test_the_verdict_is_stored_so_a_restart_does_not_replay_again(db, monkeypatch):
    run_id = record_under_other_rules(db, monkeypatch)
    reopen(db).summary(run_id)
    stored = row(db, run_id)
    assert (stored["verdict"], stored["divergence"], stored["verified_fingerprint"]) == ("diverged", 157, compat.behaviour_fingerprint())
    assert "diverged at event 157" in stored["verdict_detail"]
    monkeypatch.setattr(compat, "replay_verdict", lambda *a, **k: pytest.fail("replayed again"))
    assert reopen(db).summary(run_id)["compatibility"]["state"] == CHANGED
    assert stored["fingerprint"] == "older-behaviour0"  # the original stamp is untouched


def test_a_stored_verdict_for_other_behaviour_is_not_trusted(db, monkeypatch):
    """A verdict is about one fingerprint and one length of log. If either differs, the run is looked at again."""
    run_id = record_under_other_rules(db, monkeypatch, weight=reasoning.SELF_SERVING_TESTIMONY_WEIGHT, ticks=6)
    reopen(db).summary(run_id)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE runs SET verified_fingerprint = 'someone-elses' WHERE id = ?", (run_id,))
    calls = []
    real = compat.replay_verdict
    monkeypatch.setattr(compat, "replay_verdict", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert reopen(db).summary(run_id)["compatibility"]["state"] == VERIFIED
    assert calls == [1]
    # A log longer than the verdict covers (another build appended to it) is checked again as well.
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE runs SET verified_events = verified_events - 1 WHERE id = ?", (run_id,))
    assert reopen(db).summary(run_id)["compatibility"]["state"] == VERIFIED
    assert calls == [1, 1]


# -- branch from a run that has changed ---------------------------------------------------------


def test_a_changed_run_can_be_branched_only_where_the_current_rules_reproduce_it(db, monkeypatch):
    run_id = record_under_other_rules(db, monkeypatch)
    service = reopen(db)
    events = Store(db).load_events(run_id)
    divergence_tick = events[157].tick
    assert divergence_tick > 2

    early = service.branch(run_id, 2)
    assert early["continuable"] is True and early["parent_run_id"] == run_id
    assert early["compatibility"]["state"] == VERIFIED  # its events replay under the current rules; its stamp is the parent's
    assert early["compatibility"]["stamped_rules"] == "2026.11-older"  # the branch keeps the parent's stamp
    service.step(early["id"], 3)
    assert service.verify(early["id"])["decisions"]["ok"] is True
    assert Store(db).load_events(early["id"])[: len([e for e in events if e.tick <= 2])] == [e for e in events if e.tick <= 2]

    with pytest.raises(ContinuationRefused, match=r"Branch from a tick before event 157"):
        service.branch(run_id, 14)
    with pytest.raises(ContinuationRefused):
        service.branch(run_id, divergence_tick)
    assert len(Store(db).list_runs()) == 2  # the refused branches created nothing

    service.delete(run_id)  # nothing is kept against the user's wishes, and nothing is deleted without them
    assert [r["id"] for r in service.list_runs()] == [early["id"]]


# -- 4. explicitly incompatible runs keep their existing handling -----------------------------------


def test_a_run_from_another_engine_version_is_still_listed_with_its_reason_and_never_replayed(db, monkeypatch):
    service = RunService(Store(db))
    good = service.create_run(SCENARIO, 7)
    from caseforge.scenario import load_bundled

    scenario = load_bundled(SCENARIO)
    events = Store(db).load_events(good["id"])
    old = rehashed(events[:20], lambda data: data.update(engine_version="2"))
    service.store.create_run("oldengine", scenario.id, scenario.version, scenario.content_hash, 7, old, label="engine 2")
    monkeypatch.setattr(compat, "replay_verdict", lambda *a, **k: pytest.fail("an incompatible format must not be replayed"))

    listed = {r["id"]: r for r in reopen(db).list_runs()}
    assert listed["oldengine"]["compatible"] is False and listed["oldengine"]["continuable"] is False
    assert "engine version '2'" in listed["oldengine"]["incompatible_reason"] and listed["oldengine"]["compatibility"] is None
    assert listed[good["id"]]["continuable"] is True
    with pytest.raises(IncompatibleRun):
        reopen(db).step("oldengine", 1)
    assert Store(db).load_events("oldengine") == old


# -- 5. persistence of the stamp ---------------------------------------------------------------------


def test_a_database_from_before_stamps_opens_unchanged_and_gains_only_empty_columns(tmp_path):
    path = str(tmp_path / "old.sqlite3")
    old_schema = """
    CREATE TABLE runs (id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, scenario_version TEXT NOT NULL, scenario_hash TEXT NOT NULL,
        seed INTEGER NOT NULL, label TEXT NOT NULL DEFAULT '', parent_run_id TEXT, fork_tick INTEGER, fork_seq INTEGER,
        revealed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
    CREATE TABLE events (run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, seq INTEGER NOT NULL, tick INTEGER NOT NULL,
        type TEXT NOT NULL, actor TEXT NOT NULL, cause INTEGER, data TEXT NOT NULL, hash TEXT NOT NULL, PRIMARY KEY (run_id, seq));
    """
    source = RunService(Store(str(tmp_path / "src.sqlite3")))
    made = source.create_run(SCENARIO, 7, POLICIES)
    source.step(made["id"], 9)
    events = source.store.load_events(made["id"])
    conn = sqlite3.connect(path)
    conn.executescript(old_schema)
    conn.execute("INSERT INTO runs VALUES ('legacy01', ?, ?, ?, 7, 'before stamps', NULL, NULL, NULL, 0, '2026-11-01T00:00:00+00:00')",
                 (made["scenario_id"], made["scenario_version"], source.store.get_run(made["id"])["scenario_hash"]))
    conn.executemany("INSERT INTO events VALUES ('legacy01', ?, ?, ?, ?, ?, ?, ?)",
                     [(e.seq, e.tick, e.type, e.actor, e.cause, __import__("json").dumps(e.data, sort_keys=True, separators=(",", ":")), e.hash) for e in events])
    conn.commit()
    conn.close()
    dump_before = sqlite3.connect(path).execute("SELECT run_id, seq, hash, data FROM events ORDER BY seq").fetchall()

    service = RunService(Store(path))  # opening migrates: columns added, nothing rewritten
    columns = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(runs)")}
    assert {"rules_version", "fingerprint", "verified_fingerprint", "verified_events", "verdict", "divergence", "verdict_detail"} <= columns
    assert sqlite3.connect(path).execute("SELECT run_id, seq, hash, data FROM events ORDER BY seq").fetchall() == dump_before
    legacy = service.summary("legacy01")
    assert legacy["label"] == "before stamps" and legacy["compatibility"]["legacy"] is True
    assert legacy["compatibility"]["state"] == VERIFIED and legacy["continuable"] is True
    service.step("legacy01", 2)
    assert service.verify("legacy01")["policies"]["ok"] is True
    Store(path)  # opening a migrated database again is a no-op


def test_an_older_build_can_still_read_a_stamped_database(db):
    """Columns are only added, so a build that knows nothing about them selects what it needs."""
    service = RunService(Store(db))
    run = service.create_run(SCENARIO, 7)
    service.step(run["id"], 3)
    conn = sqlite3.connect(db)
    names = [r[1] for r in conn.execute("PRAGMA table_info(runs)")]
    assert names[:11] == ["id", "scenario_id", "scenario_version", "scenario_hash", "seed", "label", "parent_run_id", "fork_tick", "fork_seq", "revealed", "created_at"]
    assert conn.execute("SELECT COUNT(*) FROM events WHERE run_id = ?", (run["id"],)).fetchone()[0] > 0


# -- over HTTP ---------------------------------------------------------------------------------------


def test_the_api_reports_compatibility_and_answers_a_refused_continuation_with_409(db, monkeypatch):
    run_id = record_under_other_rules(db, monkeypatch)
    with TestClient(create_app(db)) as client:
        listing = {r["id"]: r for r in client.get("/api/runs").json()}[run_id]
        assert listing["continuable"] is False and listing["compatibility"]["state"] == "behaviour_changed"
        assert client.get(f"/api/runs/{run_id}/snapshot").status_code == 200
        for method, path, body in (
            ("post", f"/api/runs/{run_id}/step", {"ticks": 1}),
            ("post", f"/api/runs/{run_id}/interventions", {"intervention_id": "rumor_registrar"}),
            ("post", f"/api/runs/{run_id}/policy", {"agent": "hale", "policy": "hasty"}),
            ("post", f"/api/runs/{run_id}/branch", {"tick": 14}),
        ):
            response = getattr(client, method)(path, json=body)
            assert response.status_code == 409, path
            assert "read-only" in response.json()["detail"] or "Branch from a tick before" in response.json()["detail"]
        assert client.get(f"/api/runs/{run_id}/verify").json()["compatibility"]["first_divergence"] == 157
        created = client.post("/api/runs", json={"scenario_id": SCENARIO, "seed": 3}).json()
        assert created["continuable"] is True and created["compatibility"]["state"] == "current"
        assert client.post(f"/api/runs/{created['id']}/step", json={"ticks": 2}).status_code == 200
        assert client.delete(f"/api/runs/{run_id}").status_code == 204
