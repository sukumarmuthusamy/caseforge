"""Action rules: invalid actions change nothing; valid actions change the world."""

from __future__ import annotations

import pytest

from caseforge.engine import Engine
from caseforge.models import Accuse, Decision, DecisionTrace, Inspect, Publish, Request, Respond, Retract, Share, Wait
from caseforge.state import state_fingerprint

from .conftest import SEED, ScriptedPolicy, all_scripted, scripted_factory


def run_script(scenario, script, ticks=1):
    policy = ScriptedPolicy(script)
    engine = Engine.start(scenario, SEED, all_scripted(scenario), scripted_factory(policy))
    engine.run(ticks)
    return engine


def world(engine):
    """State with bookkeeping removed: what an invalid action must leave untouched."""
    data = state_fingerprint(engine.state)
    for key in ("seq", "head_hash", "tick", "order"):
        data.pop(key)
    for agent in data["agents"].values():
        agent.pop("actions")
        agent.pop("rejected")
    return data


INVALID = [
    ("nair", Inspect(source="access_control", topic="aurora"), "no_access"),
    ("okafor", Inspect(source="warehouse", topic="aurora"), "unknown_source"),
    ("okafor", Inspect(source="forensics_lab", topic="card0417"), "unknown_topic"),  # probing for a hidden entity
    ("okafor", Inspect(source="lab3_scene", topic="voss"), "not_searchable"),
    ("reyes", Inspect(source="mail_server", topic="whitlock"), "no_access"),  # operator, but not on his own initiative
    ("okafor", Request(to="okafor", topic="aurora"), "self_request"),
    ("okafor", Request(to="nobody", topic="aurora"), "unknown_agent"),
    ("nair", Request(to="reyes", topic="aurora", source="access_control"), "not_authorized"),
    ("okafor", Request(to="brandt", topic="aurora", source="access_control"), "not_operator"),
    ("brandt", Request(to="reyes", topic="whitlock", source="mail_server"), "not_authorized"),
    ("reyes", Respond(request_id="R999", accept=True), "unknown_request"),
    ("okafor", Share(to="brandt", evidence_id="E13"), "not_held"),
    ("brandt", Share(to="brandt", evidence_id="E03"), "unknown_agent"),
    ("okafor", Publish(proposition="has_motive(voss)"), "not_permitted"),
    ("nair", Publish(proposition="at(whitlock)"), "malformed_proposition"),
    ("nair", Publish(proposition="has_motive(card0417)"), "malformed_proposition"),
    ("nair", Publish(proposition="crime_at(lab3,oct14_2145)"), "not_publishable"),
    ("nair", Publish(proposition="has_motive(voss)", cited=("E07",)), "not_held"),
    ("nair", Retract(claim_id="C999"), "unknown_claim"),
    ("nair", Accuse(suspect="brandt"), "not_permitted"),
    ("okafor", Accuse(suspect="alvarez"), "not_a_suspect"),
    ("okafor", Accuse(suspect="brandt", cited=("E13",)), "not_held"),
]


@pytest.mark.parametrize("agent,action,code", INVALID, ids=[f"{a}-{c}" for a, _, c in INVALID])
def test_invalid_action_is_rejected_and_changes_nothing(scenario, agent, action, code):
    baseline = run_script(scenario, {})
    engine = run_script(scenario, {(1, agent): action})
    rejected = [e for e in engine.events if e.type == "ActionRejected"]
    assert len(rejected) == 1
    assert rejected[0].data["agent"] == agent and rejected[0].data["code"] == code
    assert world(engine) == world(baseline)
    assert engine.state.agents[agent].rejected == 1
    assert engine.state.status == "running"
    # A rejection produces exactly one event in place of the wait: no side effects were emitted.
    assert len(engine.events) == len(baseline.events)


def test_inspect_delivers_evidence_and_revises_beliefs(scenario):
    engine = run_script(scenario, {(1, "okafor"): Inspect(source="lab3_scene", topic="aurora")})
    okafor = engine.state.agents["okafor"]
    assert set(okafor.holdings) == {"E02"}
    assert okafor.holdings["E02"].via == "inspect" and okafor.holdings["E02"].chain == ["okafor"]
    assert okafor.beliefs["crime_at(lab3,oct14_2145)"].status == "believed"
    assert okafor.tried["lab3_scene|aurora"].found == 1
    types = [e.type for e in engine.events if e.actor == "okafor" and e.tick == 1]
    assert types == ["ActionTaken", "SourceInspected", "EvidenceObserved", "BeliefsRevised"]


def answer_first(accept):
    return lambda view: Respond(request_id=view.inbox[0].id, accept=accept)


def test_request_flow_moves_a_record_through_an_operator(scenario):
    engine = run_script(scenario, {
        (1, "okafor"): Request(to="reyes", topic="aurora", source="access_control"),
        (2, "reyes"): answer_first(True),
    }, ticks=2)
    (request,) = engine.state.requests.values()
    assert request.status == "fulfilled" and request.evidence == ["E01"]
    assert engine.state.agents["reyes"].holdings["E01"].via == "inspect"
    holding = engine.state.agents["okafor"].holdings["E01"]
    assert holding.via == "shared" and holding.from_agent == "reyes" and holding.chain == ["reyes", "okafor"]
    # Reyes ran the query on request, so it is not recorded as his own initiative.
    assert "access_control|aurora" not in engine.state.agents["reyes"].tried


def test_declined_request_delivers_nothing(scenario):
    engine = run_script(scenario, {
        (1, "nair"): Request(to="brandt", topic="brandt"),
        (2, "brandt"): answer_first(False),
    }, ticks=2)
    (request,) = engine.state.requests.values()
    assert request.status == "declined"
    assert not engine.state.agents["nair"].holdings


def test_request_ids_and_claim_ids_come_from_the_event_sequence(scenario):
    engine = run_script(scenario, {(1, "okafor"): Request(to="reyes", topic="aurora", source="access_control")})
    sent = next(e for e in engine.events if e.type == "RequestSent")
    assert sent.data["request"] == f"R{sent.seq}"


def test_prerequisite_gated_record_needs_its_basis(scenario):
    """The reader forensics exist only for someone who already knows which reader to examine."""
    engine = run_script(scenario, {(1, "okafor"): Inspect(source="forensics_lab", topic="lab3")})
    assert engine.state.agents["okafor"].tried["forensics_lab|lab3"].found == 0
    assert "E10" not in engine.state.discovered


def test_protected_source_material_cannot_be_passed_on(scenario):
    script = {
        (1, "nair"): Inspect(source="novacell_contact", topic="aurora"),
        (2, "nair"): Share(to="okafor", evidence_id="E14"),
    }
    engine = run_script(scenario, script, ticks=2)
    rejected = [e for e in engine.events if e.type == "ActionRejected"]
    assert [e.data["code"] for e in rejected] == ["not_shareable"]
    assert "E14" not in engine.state.agents["okafor"].holdings


def test_duplicate_share_and_duplicate_claim_are_rejected(scenario):
    script = {
        (1, "brandt"): Share(to="okafor", evidence_id="E03"),
        (2, "brandt"): Share(to="okafor", evidence_id="E03"),
        (1, "nair"): Inspect(source="novacell_contact", topic="aurora"),
        (2, "nair"): Publish(proposition="has_motive(whitlock)", cited=("E14",)),
        (3, "nair"): Publish(proposition="has_motive(whitlock)", cited=("E14",)),
    }
    engine = run_script(scenario, script, ticks=3)
    codes = sorted(e.data["code"] for e in engine.events if e.type == "ActionRejected")
    assert codes == ["already_shared", "duplicate_claim"]
    assert len(engine.state.claims) == 1


def test_accusation_closes_the_case_and_stops_the_tick(scenario):
    engine = run_script(scenario, {(1, "okafor"): Accuse(suspect="mercer")})
    assert engine.state.status == "closed" and engine.state.close_reason == "accusation"
    assert engine.events[-1].type == "CaseClosed"
    after = [e for e in engine.events if e.seq > engine.state.accusation["seq"]]
    assert [e.type for e in after] == ["CaseClosed"]


def test_tick_limit_closes_an_idle_case(scenario):
    engine = run_script(scenario, {}, ticks=None)
    assert engine.state.status == "closed" and engine.state.close_reason == "tick_limit"
    assert engine.state.tick == scenario.case.max_ticks


class ExplodingPolicy:
    name = "scripted"
    deterministic = True

    def decide(self, view, rng):
        raise RuntimeError("boom")


class FloatLeakingPolicy:
    name = "scripted"
    deterministic = True

    def decide(self, view, rng):
        return Decision(action=Wait(), trace=DecisionTrace(policy="scripted", reason="x", llm={"temperature": 0.7}))


@pytest.mark.parametrize("broken", [ExplodingPolicy(), FloatLeakingPolicy()], ids=["raises", "unloggable-trace"])
def test_a_broken_policy_cannot_break_the_run(scenario, broken):
    engine = Engine.start(scenario, SEED, {"okafor": "scripted"}, scripted_factory(broken))
    engine.run(3)
    assert engine.state.tick == 3 and engine.state.status == "running"
    taken = [e for e in engine.events if e.type == "ActionTaken" and e.data["agent"] == "okafor"]
    assert len(taken) == 3 and all(e.data["action"] == {"type": "wait"} for e in taken)
    assert all("policy raised" in e.data["trace"]["reason"] for e in taken)
    assert engine.state.agents["reyes"].holdings  # everyone else carried on
