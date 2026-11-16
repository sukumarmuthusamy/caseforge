"""Replay invariants: the log is the state, and the log can be checked."""

from __future__ import annotations

import copy

import pytest

from caseforge.canon import GENESIS_HASH, chain_hash
from caseforge.engine import Engine, EngineError, IncompatibleRun, branch_prefix, resimulate, verify_chain, verify_run
from caseforge.models import ENGINE_VERSION, Event
from caseforge.reasoning import revise
from caseforge.state import ReplayError, SimState, apply_event, fold, state_fingerprint
from caseforge.views import context_for_agent, items_for_agent

from .conftest import SEED


def test_fold_reproduces_live_state(solved):
    assert state_fingerprint(fold(solved.events)) == state_fingerprint(solved.state)


def test_fold_matches_live_state_at_every_tick(scenario):
    engine = Engine.start(scenario, SEED)
    while engine.state.status == "running":
        engine.step()
        assert state_fingerprint(fold(engine.events)) == state_fingerprint(engine.state)
        prefix = [e for e in engine.events if e.tick <= engine.state.tick]
        assert len(prefix) == len(engine.events)


def test_hash_chain_detects_tampering(solved):
    events = list(solved.events)
    assert verify_chain(events) is None
    target = next(e for e in events if e.type == "EvidenceObserved")
    forged = Event(**{**target.model_dump(), "data": {**target.data, "agent": "nair"}})
    events[target.seq] = forged
    assert verify_chain(events) == target.seq


def test_hash_chain_detects_removed_event(solved):
    events = solved.events[:10] + solved.events[11:]
    assert verify_chain(events) == 10


def test_reducer_rejects_out_of_order_events(solved):
    state = SimState()
    apply_event(state, solved.events[0])
    with pytest.raises(ReplayError):
        apply_event(state, solved.events[2])


def test_all_verification_levels_pass_for_a_baseline_run(scenario, solved):
    report = verify_run(scenario, solved.events)
    assert report["chain"]["ok"] and report["fold"]["ok"]
    assert report["decisions"]["ok"] is True
    assert report["policies"]["ok"] is True
    assert report["head_hash"] == solved.state.head_hash


def test_resimulation_reports_divergence(scenario, solved):
    """A log whose recorded decision was altered no longer reproduces."""
    events = list(solved.events)
    target = next(e for e in events if e.type == "ActionTaken" and e.data["action"]["type"] == "inspect")
    altered = Event(**{**target.model_dump(), "data": {**target.data, "action": {"type": "wait"}}})
    events[target.seq] = altered
    report = resimulate(scenario, events, "decisions")
    assert report["ok"] is False and report["first_divergence"] is not None


def test_recorded_beliefs_equal_recomputed_beliefs(scenario, solved):
    """The reducer applies recorded diffs; recomputing from holdings must agree."""
    for agent_id, agent in solved.state.agents.items():
        fresh = revise(items_for_agent(scenario, solved.state, agent_id), context_for_agent(scenario, agent_id))
        assert agent.beliefs == fresh.beliefs
        assert agent.suspects == fresh.suspects
        assert agent.prime_suspect == fresh.prime_suspect
        # Recognized contradictions are remembered even after they are resolved.
        assert set(fresh.contradictions) <= set(agent.contradictions)


def test_every_belief_revision_names_its_trigger(solved):
    by_seq = {e.seq: e for e in solved.events}
    revisions = [e for e in solved.events if e.type == "BeliefsRevised"]
    assert revisions
    for event in revisions:
        assert event.data["because"], event
        assert event.cause is not None
        assert by_seq[event.cause].type in ("RunStarted", "ActionTaken", "InterventionApplied")


def rehashed(events, change):
    """A copy of a log with its first event altered and every hash recomputed: still a valid chain."""
    out, prev = [], GENESIS_HASH
    for event in events:
        body = copy.deepcopy(event.body())
        if event.seq == 0:
            change(body["data"])
        out.append(Event(**body, hash=chain_hash(prev, body)))
        prev = out[-1].hash
    return out


def test_engine_refuses_log_from_another_scenario_version(scenario, solved):
    altered = rehashed(solved.events, lambda data: data.update(scenario_hash="f" * 64))
    assert verify_chain(altered) is None
    with pytest.raises(IncompatibleRun, match="different version of the scenario"):
        Engine(scenario, altered)


def test_engine_refuses_log_from_another_engine_version(scenario, solved):
    """A validly chained log from another engine version is neither folded nor continued."""
    altered = rehashed(solved.events[:20], lambda data: data.update(engine_version="999-incompatible"))
    assert verify_chain(altered) is None
    with pytest.raises(IncompatibleRun, match="engine version '999-incompatible'"):
        Engine(scenario, altered)
    assert issubclass(IncompatibleRun, EngineError)  # the API answers 409, not 500


def test_engine_version_is_recorded_and_restored(scenario, solved):
    assert solved.events[0].data["engine_version"] == ENGINE_VERSION
    assert solved.state.engine_version == ENGINE_VERSION == fold(solved.events).engine_version
    resumed = Engine(scenario, solved.events[:20])  # the current version resumes normally
    assert resumed.state.seq == 19


def test_branch_prefix_bounds(solved):
    assert branch_prefix(solved.events, 0)[-1].tick == 0
    with pytest.raises(EngineError):
        branch_prefix(solved.events, solved.state.tick + 5)
    with pytest.raises(EngineError):
        branch_prefix(solved.events, solved.state.tick)  # closed at the final tick


def test_unperturbed_branch_replays_its_parent(scenario, solved):
    branch = Engine(scenario, branch_prefix(solved.events, 6))
    assert branch.state.status == "running" and branch.state.tick == 6
    branch.run()
    assert branch.state.head_hash == solved.state.head_hash


def test_intervention_makes_a_branch_diverge_and_leaves_parent_alone(scenario, solved):
    parent_hashes = [e.hash for e in solved.events]
    branch = Engine(scenario, branch_prefix(solved.events, 2))
    branch.intervene("leak_door_log")
    branch.run()
    assert branch.state.head_hash != solved.state.head_hash
    assert [e.hash for e in solved.events] == parent_hashes
    report = verify_run(scenario, branch.events)
    assert report["decisions"]["ok"] and report["policies"]["ok"]


def test_intervention_rules(scenario):
    engine = Engine.start(scenario, SEED)
    before = len(engine.events)
    with pytest.raises(EngineError):
        engine.intervene("no_such_thing")
    assert len(engine.events) == before
    engine.intervene("rumor_contractor")
    with pytest.raises(EngineError):
        engine.intervene("rumor_contractor")
    engine.run()
    with pytest.raises(EngineError):
        engine.intervene("leak_door_log")
    with pytest.raises(EngineError):
        engine.step()
