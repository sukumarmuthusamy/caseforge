"""Persistence: the stored log is complete, never duplicated, and resumable."""

from __future__ import annotations

import pytest

import caseforge.engine as engine_module
from caseforge.engine import Engine, EngineError
from caseforge.service import NotFound, RunService
from caseforge.state import fold, state_fingerprint
from caseforge.store import Store, StoreError

from .conftest import SCENARIO_ID, SEED


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "runs.sqlite3"


def test_events_round_trip_through_sqlite(scenario, solved, db):
    store = Store(db)
    store.create_run("r1", scenario.id, scenario.version, scenario.content_hash, SEED, solved.events)
    loaded = store.load_events("r1")
    assert loaded == solved.events
    assert state_fingerprint(fold(loaded)) == state_fingerprint(solved.state)
    row = store.get_run("r1")
    assert row["last_seq"] == solved.state.seq and row["closed"] == 1 and row["head_hash"] == solved.state.head_hash


def test_store_refuses_duplicates_and_gaps(scenario, solved, db):
    store = Store(db)
    store.create_run("r1", scenario.id, scenario.version, scenario.content_hash, SEED, solved.events[:10])
    with pytest.raises(StoreError):
        store.append_events("r1", solved.events[5:12])  # overlaps what is stored
    with pytest.raises(StoreError):
        store.append_events("r1", solved.events[12:15])  # skips seq 10 and 11
    assert len(store.load_events("r1")) == 10
    store.append_events("r1", solved.events[10:15])
    assert [e.seq for e in store.load_events("r1")] == list(range(15))


def test_resuming_with_a_new_service_matches_an_uninterrupted_run(scenario, solved, db):
    """A second service on the same file, in the same interpreter: this proves reconstruction from disk, not process isolation."""
    first = RunService(Store(db))
    run = first.create_run(SCENARIO_ID, SEED)
    first.step(run["id"], 5)
    assert first.summary(run["id"])["tick"] == 5

    second = RunService(Store(db))  # nothing shared with `first` but the file
    assert second.summary(run["id"])["tick"] == 5
    while second.summary(run["id"])["status"] == "running":
        second.step(run["id"], 3)

    stored = Store(db).load_events(run["id"])
    assert [e.seq for e in stored] == list(range(len(stored)))  # contiguous, nothing duplicated
    assert stored[-1].hash == solved.state.head_hash
    assert [e.hash for e in stored] == [e.hash for e in solved.events]


def test_branch_is_a_separate_run_with_lineage(scenario, solved, db):
    service = RunService(Store(db))
    parent = service.create_run(SCENARIO_ID, SEED, label="original")
    service.step(parent["id"], 100)
    parent_events = service.events(parent["id"])

    branch = service.branch(parent["id"], 4)
    assert branch["parent_run_id"] == parent["id"] and branch["fork_tick"] == 4
    assert branch["tick"] == 4 and branch["status"] == "running"
    assert "original" in branch["label"]

    service.intervene(branch["id"], "leak_door_log")
    service.step(branch["id"], 100)
    assert service.summary(branch["id"])["head_hash"] != service.summary(parent["id"])["head_hash"]
    assert service.events(parent["id"]) == parent_events  # the parent is untouched

    comparison = service.compare(parent["id"], branch["id"])
    assert comparison["identical"] is False
    assert comparison["divergence"]["tick"] == 4
    assert comparison["divergence"]["b"][0]["type"] == "InterventionApplied"
    assert comparison["common_events"] == len([e for e in parent_events if e["tick"] <= 4])

    twin = service.branch(parent["id"], 4)
    service.step(twin["id"], 100)
    assert service.compare(parent["id"], twin["id"])["identical"] is True


def test_branching_a_closed_tick_is_refused(db):
    service = RunService(Store(db))
    run = service.create_run(SCENARIO_ID, SEED)
    service.step(run["id"], 100)
    with pytest.raises(EngineError):
        service.branch(run["id"], service.summary(run["id"])["tick"])
    assert len(service.list_runs()) == 1


def test_failure_mid_tick_leaves_the_stored_run_consistent(scenario, solved, db, monkeypatch):
    service = RunService(Store(db))
    run = service.create_run(SCENARIO_ID, SEED)
    service.step(run["id"], 2)
    before = Store(db).load_events(run["id"])

    real = engine_module.apply_action
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("disk on fire")
        return real(*args, **kwargs)

    monkeypatch.setattr(engine_module, "apply_action", flaky)
    with pytest.raises(RuntimeError):
        service.step(run["id"], 4)

    # Nothing from the failed call was stored, not even its completed ticks.
    assert Store(db).load_events(run["id"]) == before
    assert service.summary(run["id"])["tick"] == 2

    monkeypatch.setattr(engine_module, "apply_action", real)
    service.step(run["id"], 100)
    assert service.summary(run["id"])["head_hash"] == solved.state.head_hash
    assert service.verify(run["id"])["stored_matches_memory"] is True


def test_failed_intervention_appends_nothing(db):
    service = RunService(Store(db))
    run = service.create_run(SCENARIO_ID, SEED)
    seq = service.summary(run["id"])["seq"]
    with pytest.raises(EngineError):
        service.intervene(run["id"], "does_not_exist")
    service.intervene(run["id"], "rumor_contractor")
    with pytest.raises(EngineError):
        service.intervene(run["id"], "rumor_contractor")
    stored = Store(db).load_events(run["id"])
    assert [e.type for e in stored[seq + 1 :]].count("InterventionApplied") == 1


def test_unknown_run_and_delete(db):
    service = RunService(Store(db))
    with pytest.raises(NotFound):
        service.summary("nope")
    run = service.create_run(SCENARIO_ID, SEED)
    service.delete(run["id"])
    with pytest.raises(NotFound):
        service.snapshot(run["id"])
    assert Store(db).load_events(run["id"]) == []


def test_incompatible_stored_run_is_listed_refused_and_deletable(scenario, solved, db):
    """At the service boundary: an old run cannot be opened or continued, and does not break the list."""
    from caseforge.engine import IncompatibleRun

    from .test_replay import rehashed

    service = RunService(Store(db))
    good = service.create_run(SCENARIO_ID, SEED)
    old = rehashed(solved.events[:30], lambda data: data.update(engine_version="1"))
    service.store.create_run("oldrun01", scenario.id, scenario.version, scenario.content_hash, SEED, old, label="from engine 1")

    listed = {run["id"]: run for run in service.list_runs()}
    assert listed[good["id"]]["compatible"] is True and listed[good["id"]]["incompatible_reason"] is None
    stale = listed["oldrun01"]
    assert stale["compatible"] is False and "engine version '1'" in stale["incompatible_reason"]
    assert stale["seq"] == 29 and stale["label"] == "from engine 1"

    for operation in (
        lambda: service.step("oldrun01", 1),
        lambda: service.snapshot("oldrun01"),
        lambda: service.branch("oldrun01", 1),
        lambda: service.verify("oldrun01"),
        lambda: service.intervene("oldrun01", "rumor_contractor"),
    ):
        with pytest.raises(IncompatibleRun):
            operation()
    assert Store(db).load_events("oldrun01") == old  # nothing was appended or rewritten

    service.delete("oldrun01")
    assert [run["id"] for run in service.list_runs()] == [good["id"]]


def test_run_with_unavailable_policy_is_never_created(db, monkeypatch):
    monkeypatch.delenv("CASEFORGE_LLM_ENABLED", raising=False)
    service = RunService(Store(db))
    with pytest.raises(EngineError):
        service.create_run(SCENARIO_ID, SEED, {"okafor": "llm"})
    with pytest.raises(EngineError):
        service.create_run(SCENARIO_ID, SEED, {"okafor": "no_such_policy"})
    assert service.list_runs() == []


def test_time_travel_snapshot_equals_fold_of_prefix(scenario, solved, db):
    service = RunService(Store(db))
    run = service.create_run(SCENARIO_ID, SEED)
    service.step(run["id"], 100)
    past = service.snapshot(run["id"], 6)
    assert past["tick"] == 6 and past["is_latest"] is False and past["latest_tick"] == solved.state.tick
    expected = fold([e for e in solved.events if e.tick <= 6])
    assert set(past["evidence"]) == set(expected.discovered)
    assert past["status"] == "running" and past["run"]["status"] == "closed"
    latest = service.snapshot(run["id"])
    assert latest["is_latest"] is True and set(past["evidence"]) < set(latest["evidence"])


def test_a_tampered_stored_log_is_refused_on_load(scenario, db):
    """The hash chain is checked when a run is loaded, not only on explicit verification."""
    import sqlite3

    from caseforge.engine import IncompatibleRun

    first = RunService(Store(db))
    run = first.create_run(SCENARIO_ID, SEED)
    first.step(run["id"], 3)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE events SET data = replace(data, '\"seed\":7', '\"seed\":8') WHERE run_id = ? AND seq = 0", (run["id"],))
    conn.close()

    second = RunService(Store(db))  # nothing cached
    (listed,) = second.list_runs()
    assert listed["compatible"] is False and "hash chain is broken at event 0" in listed["incompatible_reason"]
    with pytest.raises(IncompatibleRun, match="damaged"):
        second.step(run["id"], 1)
    assert len(Store(db).load_events(run["id"])) == len(first._engines[run["id"]].events)  # nothing appended


# -- the events and the coverage that describes them are one transaction ------------------
#
# The fault is injected in the database, not by patching a method of the code under test, so these tests
# prove where the transaction boundary is rather than the order of two calls.

FAIL_COVERAGE = (
    "CREATE TRIGGER fail_coverage BEFORE UPDATE OF verified_events ON runs "
    "BEGIN SELECT RAISE(ABORT, 'injected coverage failure'); END"
)


def _sql(db, statement):
    import sqlite3
    from contextlib import closing

    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute(statement)


def test_store_append_and_coverage_commit_together_or_not_at_all(scenario, solved, db):
    from caseforge.compat import behaviour_fingerprint

    store = Store(db)
    store.create_run("r1", scenario.id, scenario.version, scenario.content_hash, SEED, solved.events[:10])
    fingerprint = behaviour_fingerprint()
    assert store.get_run("r1")["verified_events"] == 10

    _sql(db, FAIL_COVERAGE)
    with pytest.raises(StoreError, match="injected coverage failure"):
        store.append_events("r1", solved.events[10:15], verified=(fingerprint, 15))
    assert len(store.load_events("r1")) == 10  # the insert was rolled back with the failed update
    assert store.get_run("r1")["verified_events"] == 10

    _sql(db, "DROP TRIGGER fail_coverage")
    store.append_events("r1", solved.events[10:15], verified=(fingerprint, 15))
    assert len(store.load_events("r1")) == 15
    assert store.get_run("r1")["verified_events"] == 15


def test_coverage_extends_only_a_run_verified_under_this_fingerprint(scenario, solved, db):
    """A run with no verdict under this build matches no row: the append still succeeds and the run is replayed on its next load."""
    store = Store(db)
    store.create_run("r1", scenario.id, scenario.version, scenario.content_hash, SEED, solved.events[:10])
    store.set_verdict("r1", "some-other-fingerprint", 10, "ok", None, "")
    from caseforge.compat import behaviour_fingerprint

    store.append_events("r1", solved.events[10:15], verified=(behaviour_fingerprint(), 15))
    row = store.get_run("r1")
    assert len(store.load_events("r1")) == 15
    assert row["verified_events"] == 10 and row["verified_fingerprint"] == "some-other-fingerprint"


def test_a_failed_coverage_write_is_a_clean_failure_that_can_be_retried(scenario, db, monkeypatch):
    import caseforge.compat as compat

    service = RunService(Store(db))
    run = service.create_run("quiet_substitution", SEED)
    rid = run["id"]
    initial = len(Store(db).load_events(rid))

    control = RunService(Store(db.parent / "control.sqlite3"))
    control_run = control.create_run("quiet_substitution", SEED)
    control.step(control_run["id"], 1)
    expected_head = control.summary(control_run["id"])["head_hash"]

    _sql(db, FAIL_COVERAGE)
    with pytest.raises(StoreError, match="injected coverage failure"):
        service.step(rid, 1)
    # Neither the events nor the coverage advanced, in the database or in this service.
    assert len(Store(db).load_events(rid)) == initial
    assert Store(db).get_run(rid)["verified_events"] == initial
    assert rid not in service._engines

    # A new service on the same file recovers consistently, and needs no replay to do it.
    def no_replay(*args, **kwargs):
        raise AssertionError("the stored verdict should still cover the stored log")

    monkeypatch.setattr(compat, "replay_verdict", no_replay)
    reopened = RunService(Store(db))
    summary = reopened.summary(rid)
    assert summary["tick"] == 0 and summary["seq"] == initial - 1
    assert summary["compatibility"]["state"] == "current" and summary["continuable"] is True
    monkeypatch.undo()

    # Retrying is a first attempt: exactly one step, identical to an uninterrupted run.
    _sql(db, "DROP TRIGGER fail_coverage")
    service.step(rid, 1)
    assert service.summary(rid)["tick"] == 1
    assert service.summary(rid)["head_hash"] == expected_head
    assert Store(db).get_run(rid)["verified_events"] == len(Store(db).load_events(rid))
    assert service.verify(rid)["stored_matches_memory"] is True
    assert RunService(Store(db)).summary(rid)["head_hash"] == expected_head


def test_ordinary_operations_keep_coverage_in_step_with_the_log(db):
    service = RunService(Store(db))
    run = service.create_run(SCENARIO_ID, SEED)
    rid = run["id"]
    service.step(rid, 2)
    service.intervene(rid, "rumor_contractor")
    service.set_policy(rid, "okafor", "hasty")
    branch = service.branch(rid, 1)
    service.step(branch["id"], 2)
    for run_id in (rid, branch["id"]):
        row = Store(db).get_run(run_id)
        assert row["verified_events"] == len(Store(db).load_events(run_id)) and row["verdict"] == "ok"
    # Restart: nothing needs replaying and nothing is refused.
    again = RunService(Store(db))
    assert all(r["continuable"] and r["compatibility"]["state"] == "current" for r in again.list_runs())
