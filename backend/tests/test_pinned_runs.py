"""Reference runs with their head hashes pinned.

A head hash identifies every event of a run, so these pins say one thing only:
the behaviour of the bundled policies, the reasoner and the bundled scenarios
did not change by accident. They do not say the behaviour is right.

When a pin fails after an intended change:

1. Runs stored before the change no longer re-simulate (the "policies" level
   of verification fails for them), or stop loading if a scenario's content
   changed. Decide whether that is acceptable; a reducer change also needs a
   new ENGINE_VERSION (docs/EVENT_MODEL.md).
2. Re-measure the sweep tables in README.md.
3. Replace the pins with the values printed by the failure.

The digest of a condition covers seeds 0, 3 and 7.

History of the pins:

- Engine version 2, scenarios 1.1.0 / 1.0.0: first pinned.
- Engine version 3 (testimony and credibility), quiet_substitution 1.1.0: every
  pin replaced, because every log now starts with a different engine version
  and records credibility. What that change did to the runs was measured
  first, on seeds 0-39 of all eighteen documented conditions, against the
  build before it:
    * missing_prototype: 320 of 320 runs have the same events in the same
      order once the new event types (CredibilityRevised, StatementMade,
      StatementWeighed) are left out. Same decisions, same beliefs, same
      outcomes.
    * quiet_substitution with the credibility rule alone (scenario 1.0.0):
      400 of 400 runs keep their outcome, accused, support and tick count.
      Beliefs differ where a speaker was caught out.
    * quiet_substitution 1.1.0 (two agents now have something they saw and
      say it): runs differ, as intended. The numbers are in README.md.
- Rules 2026.11-voices (a review correction: one voice counts once per zone, not
  once per spot named in it): no pin changed. All 720 documented runs (both
  scenarios, eighteen conditions, seeds 0-39) kept their head hash, so the
  engine version stayed at 3. `test_no_bundled_run_can_reach_the_corrected_rule`
  says why: nothing in either case lets one voice name two spots in one zone
  for the same person and time.
"""

from __future__ import annotations

import hashlib

import pytest

from caseforge.__main__ import run_investigation
from caseforge.scenario import load_bundled

SEEDS = (0, 3, 7)

# (scenario, label, policies, [(tick, intervention)]) -> digest
PINS = [
    ("missing_prototype", "baseline", {}, [], "e101f4d20351f625"),
    ("missing_prototype", "hasty detective", {"okafor": "hasty"}, [], "6520aaeabe319ab6"),
    ("missing_prototype", "door log leaked", {}, [(0, "leak_door_log")], "2ab390170f98b6c4"),
    ("missing_prototype", "rumor", {}, [(0, "rumor_contractor")], "4c04230fbad64fbe"),
    ("missing_prototype", "forensics and access", {}, [(0, "fast_track_forensics"), (0, "grant_systems_access")], "b10cdf97b5ea2603"),
    ("missing_prototype", "deceptive technician", {"reyes": "deceptive"}, [], "b52c3363c662f3e2"),
    ("missing_prototype", "deceptive, hasty", {"reyes": "deceptive", "okafor": "hasty"}, [], "20eb3759a99d6a49"),
    ("missing_prototype", "deceptive, access", {"reyes": "deceptive"}, [(0, "grant_systems_access")], "3278269aaf5691ed"),
    ("quiet_substitution", "baseline", {}, [], "d4133830003ce178"),
    ("quiet_substitution", "hasty inspector", {"hale": "hasty"}, [], "bf18a72eb191df10"),
    ("quiet_substitution", "conservator volunteers", {}, [(0, "volunteer_statement")], "2778b677684de4d1"),
    ("quiet_substitution", "logger released", {}, [(0, "release_logger")], "ebde7f1a399f3633"),
    ("quiet_substitution", "rumor", {}, [(0, "rumor_registrar")], "3d07dfcdfc90b98d"),
    ("quiet_substitution", "security access", {}, [(0, "grant_security_access")], "f44682e5ad5b8d76"),
    ("quiet_substitution", "deceptive registrar", {"ibarra": "deceptive"}, [], "e6019ffbef0d41ab"),
    ("quiet_substitution", "deceptive, hasty", {"ibarra": "deceptive", "hale": "hasty"}, [], "7fa75360699eb311"),
]


def digest(scenario_id: str, policies: dict[str, str], schedule: list[tuple[int, str]]) -> str:
    scenario = load_bundled(scenario_id)
    heads = [run_investigation(scenario, seed, policies, sorted(schedule)).state.head_hash for seed in SEEDS]
    return hashlib.sha256("\n".join(heads).encode()).hexdigest()[:16]


@pytest.mark.parametrize("scenario_id, label, policies, schedule, pinned", PINS, ids=[f"{p[0]}: {p[1]}" for p in PINS])
def test_reference_runs_have_not_changed(scenario_id, label, policies, schedule, pinned):
    actual = digest(scenario_id, policies, schedule)
    assert actual == pinned, f'{scenario_id} / {label}: runs changed; if intended, see this module\'s docstring and pin "{actual}"'


def test_no_bundled_run_can_reach_the_corrected_rule():
    """Why rules 2026.11-voices left every stored run of the bundled cases valid.

    The correction only matters when one voice (or hearsay) places the same
    person, in the same time slot, at two different spots of one zone. In the
    bundled cases that cannot arise from the records, and the deterministic
    policies only state what an agent saw (or, lying, the spot the liar saw
    itself in), so it cannot arise from statements either. A model-backed
    agent could say such a thing; a run where one did would no longer pass
    decision replay, and `verify` would report it.
    """
    for scenario_id in ("missing_prototype", "quiet_substitution"):
        scenario = load_bundled(scenario_id)
        zone = {e.id: (e.zone or e.id) for e in scenario.entities.values() if e.kind == "location"}
        spots: dict[tuple, set[str]] = {}
        for record in scenario.private.evidence:
            if record.kind not in ("testimony", "hearsay"):
                continue
            voice = "hearsay" if record.kind == "hearsay" else record.speaker
            for prop in record.asserts:
                if prop.predicate == "at":
                    person, location, slot = prop.args
                    spots.setdefault((voice, person, slot, zone[location]), set()).add(location)
        for agent_id, seen in scenario.private.observations.items():
            for prop in seen:
                if prop.predicate == "at":
                    _person, location, slot = prop.args
                    # Whoever the agent speaks of, it names a spot it saw: one per zone and slot.
                    spots.setdefault((agent_id, "*", slot, zone[location]), set()).add(location)
        assert all(len(locations) == 1 for locations in spots.values()), scenario_id
