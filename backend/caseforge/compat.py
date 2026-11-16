"""Whether a stored run may be continued by this build.

The problem
-----------
The event log is hash-chained and its beliefs were computed by whichever
reasoner recorded them. `ENGINE_VERSION` guards the event *format*. It cannot
guard behaviour: a change to the reasoner that leaves the reducer alone lets an
older log load, fold and verify its chain, and then continue under different
rules, so the later part of one run would be judged by rules the earlier part
never saw. Manual `verify` detected
it; nothing stopped it.

The mechanism (DECISIONS D25)
-----------------------------
1. **The gate is a replay, not a label.** A run may continue only if feeding its
   recorded decisions back through *this* build's engine and reasoner reproduces
   every recorded event hash (`engine.resimulate(..., "decisions")`). That is a
   property of the log and the code together, so it cannot be fooled by a version
   string someone forgot to bump. Policies are deliberately not part of the gate:
   a policy that would decide differently today does not make the recorded past
   untrue, and a user may switch an agent's policy at any time anyway.
2. **A stamp makes the common case free.** Every run records, in the store's
   metadata, the rule set (`RULES_VERSION`) and a fingerprint of the sources that
   decide how a log is replayed (`behaviour_fingerprint`). While the fingerprint
   matches, nothing needs replaying. When it differs, or when the run has no
   stamp (a legacy run), the replay is done once and its verdict is stored with
   the fingerprint and the number of events it covered.
3. **The stamp lives outside the hash chain.** Putting it in `RunStarted` would
   change the head hash of every new run, invalidating the 720 documented
   hashes, the pinned runs and the laboratory's recorded results for no
   behavioural reason. Labels, lineage and the reveal flag are already kept
   outside the chain for the same reason.
4. **Three outcomes.** `current` (stamped by this behaviour), `verified`
   (different or missing stamp, replay reproduces the log: continuable) and
   `behaviour_changed` (replay diverges: the run stays listed and readable, can
   be verified and branched from before the divergence, and cannot be
   continued). Incompatible-format runs (engine version, scenario hash, broken
   chain) keep their existing refusal.
5. Nothing is rewritten. A verdict is only ever added next to a run.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from importlib import resources
from typing import Any

from .engine import EngineError, resimulate
from .models import ENGINE_VERSION, Event
from .reasoning import RULES_VERSION
from .scenario import Scenario

# What decides whether a recorded log replays to the same events. Policies are left out on
# purpose (see the module docstring). The laboratory has its own, differently scoped
# fingerprint, registered in its manifest.
REPLAY_SOURCES = ("reasoning.py", "engine.py", "actions.py", "state.py", "views.py", "models.py")

CURRENT = "current"
VERIFIED = "verified"
CHANGED = "behaviour_changed"


class ContinuationRefused(EngineError):
    """The run is readable but this build will not add to it. Reported as a conflict (409)."""


def source_fingerprint(names: tuple[str, ...]) -> str:
    """A short hash of package source files, independent of line endings."""
    digest = hashlib.sha256()
    for name in names:
        text = resources.files("caseforge").joinpath(*name.split("/")).read_text(encoding="utf-8").replace("\r\n", "\n")
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(text.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


_FINGERPRINT: str | None = None


def behaviour_fingerprint() -> str:
    global _FINGERPRINT
    if _FINGERPRINT is None:
        _FINGERPRINT = source_fingerprint(REPLAY_SOURCES)
    return _FINGERPRINT


def current_stamp() -> dict[str, str]:
    return {"engine_version": ENGINE_VERSION, "rules_version": RULES_VERSION, "fingerprint": behaviour_fingerprint()}


@dataclass(frozen=True)
class Compatibility:
    """What this build may do with one stored run."""

    state: str  # current | verified | behaviour_changed
    continuable: bool
    legacy: bool  # the run carries no stamp: it was stored before stamps existed
    stamped_rules: str | None
    stamped_fingerprint: str | None
    first_divergence: int | None  # seq of the first event the current rules would not have produced
    detail: str

    def public(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "continuable": self.continuable,
            "legacy": self.legacy,
            "stamped_rules": self.stamped_rules,
            "current_rules": RULES_VERSION,
            "stamped_fingerprint": self.stamped_fingerprint,
            "current_fingerprint": behaviour_fingerprint(),
            "first_divergence": self.first_divergence,
            "detail": self.detail,
        }


def replay_verdict(scenario: Scenario, events: list[Event]) -> dict[str, Any]:
    """The gate: do this build's engine and reasoner reproduce every recorded event?"""
    check = resimulate(scenario, events, "decisions")
    return {"ok": bool(check["ok"]), "divergence": check["first_divergence"], "detail": check["detail"]}


def assess(scenario: Scenario, events: list[Event], row: dict[str, Any], store: Any) -> Compatibility:
    """Judge a stored run, replaying it only when its stored verdict does not cover it.

    `row` is the run's metadata; `store` receives the verdict (additive, never a rewrite).
    """
    fingerprint = behaviour_fingerprint()
    stamped_rules = row.get("rules_version")
    stamped = row.get("fingerprint")
    legacy = stamped is None
    covered = row.get("verified_fingerprint") == fingerprint and row.get("verified_events") == len(events) and row.get("verdict") is not None
    if covered:
        ok, divergence, detail = row["verdict"] == "ok", row.get("divergence"), row.get("verdict_detail") or ""
    else:
        verdict = replay_verdict(scenario, events)
        ok, divergence, detail = verdict["ok"], verdict["divergence"], verdict["detail"]
        store.set_verdict(row["id"], fingerprint, len(events), "ok" if ok else "diverged", divergence, detail)

    if ok:
        if stamped == fingerprint:
            return Compatibility(CURRENT, True, False, stamped_rules, stamped, None, f"recorded by this behaviour (rules {stamped_rules})")
        origin = "recorded before runs carried a stamp" if legacy else f"recorded under rules {stamped_rules}"
        return Compatibility(VERIFIED, True, legacy, stamped_rules, stamped, None,
                             f"{origin}; replaying it under rules {RULES_VERSION} reproduces all {len(events)} events exactly")
    where = f"event {divergence} ({events[divergence].type})" if divergence is not None and divergence < len(events) else "an event"
    origin = "recorded before runs carried a stamp" if legacy else f"recorded under rules {stamped_rules}"
    return Compatibility(
        CHANGED, False, legacy, stamped_rules, stamped, divergence,
        f"{origin}; replaying it under rules {RULES_VERSION} diverges at {where}. Continuing would judge the rest of the run by rules "
        "the first part never saw, so it is read-only: you can view it, verify it, and branch from before the divergence",
    )
