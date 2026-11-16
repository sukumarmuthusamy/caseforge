"""The scenario lint proves the mystery is well-formed and solvable."""

from __future__ import annotations

import copy
import json
import re
from importlib import resources

import pytest

from caseforge.models import ScenarioPrivate, ScenarioPublic
from caseforge.reasoning import meets_standard, revise
from caseforge.scenario import Scenario, lint, load_scenario_data


@pytest.fixture(scope="module")
def raw() -> dict:
    text = resources.files("caseforge").joinpath("scenarios", "missing_prototype.json").read_text(encoding="utf-8")
    return json.loads(text)


def build(data: dict) -> Scenario:
    return Scenario(ScenarioPublic.model_validate(data["public"]), ScenarioPrivate.model_validate(data["private"]))


def evidence(data: dict, evidence_id: str) -> dict:
    return next(e for e in data["private"]["evidence"] if e["id"] == evidence_id)


def test_bundled_scenario_passes_lint(scenario):
    assert lint(scenario) == []


def test_scenario_has_the_designed_shape(scenario):
    assert len(scenario.agents) == 4
    assert {a.role for a in scenario.public.agents} == {"detective", "researcher", "technician", "journalist"}
    assert 10 <= len(scenario.evidence) <= 20
    assert all(re.fullmatch(r"E\d\d", e) for e in scenario.evidence), "evidence ids must be opaque"
    assert scenario.truth.culprit not in scenario.agents  # decision D10


def test_full_evidence_identifies_the_culprit_with_a_clear_margin(scenario):
    r = revise([scenario.item_for(e) for e in scenario.evidence], scenario.reasoning_context())
    assert r.prime_suspect == scenario.truth.culprit
    assert meets_standard(r.suspects, scenario.truth.culprit)
    others = [a.score for name, a in r.suspects.items() if name != scenario.truth.culprit]
    assert max(others) < 0  # every innocent suspect ends with a net exculpatory picture


def test_key_evidence_is_sufficient_even_against_the_culprits_denial(scenario):
    ids = list(scenario.truth.key_evidence) + ["E16"]
    r = revise([scenario.item_for(e) for e in ids], scenario.reasoning_context())
    assert meets_standard(r.suspects, scenario.truth.culprit)


def test_no_single_record_solves_the_case(scenario):
    for evidence_id in scenario.evidence:
        r = revise([scenario.item_for(evidence_id)], scenario.reasoning_context())
        assert not any(meets_standard(r.suspects, s) for s in scenario.case.suspects), evidence_id


def test_scenario_contains_real_contradictions_and_a_red_herring(scenario):
    everything = revise([scenario.item_for(e) for e in scenario.evidence], scenario.reasoning_context())
    assert len(everything.contradictions) >= 2
    early = revise([scenario.item_for(e) for e in ("E01", "E09")], scenario.reasoning_context())
    assert early.prime_suspect == "brandt" and meets_standard(early.suspects, "brandt")  # the trap a hasty detective falls into


def test_truth_values(scenario):
    from caseforge.models import Proposition as P

    assert scenario.truth_value(P.parse("took(whitlock,aurora)")) is True
    assert scenario.truth_value(P.parse("took(brandt,aurora)")) is False
    assert scenario.truth_value(P.parse("at(mercer,east_corridor,oct14_2145)")) is False
    assert scenario.truth_value(P.parse("at(mercer,rooftop,oct14_2145)")) is True
    assert scenario.truth_value(P.parse("at(alvarez,east_corridor,oct14_2145)")) is None  # truth is silent
    assert scenario.truth_value(P.parse("has_motive(mercer)")) is False


def mutate(raw: dict, change) -> list[str]:
    data = copy.deepcopy(raw)
    change(data)
    return lint(build(data))


def test_lint_rejects_a_record_that_lies(raw):
    def change(data):
        evidence(data, "E05")["asserts"] = ["at(mercer,east_corridor,oct14_2145)"]

    assert any("E05" in p and "not true" in p for p in mutate(raw, change))


def test_lint_rejects_inconsistent_truth(raw):
    def change(data):
        data["private"]["truth"]["facts"].append("at(whitlock,rooftop,oct14_2145)")

    assert any("two zones" in p for p in mutate(raw, change))


def test_lint_rejects_culprit_outside_suspect_list(raw):
    def change(data):
        data["private"]["truth"]["culprit"] = "alvarez"

    assert any("culprit" in p for p in mutate(raw, change))


def test_lint_rejects_dangling_references_and_bad_argument_kinds(raw):
    def change(data):
        evidence(data, "E02")["source"] = "nowhere"
        evidence(data, "E07")["asserts"] = ["has_motive(lab3)"]

    problems = mutate(raw, change)
    assert any("nowhere" in p for p in problems) and any("expects a person" in p for p in problems)


def test_lint_rejects_unreachable_evidence(raw):
    def change(data):
        evidence(data, "E15")["mentions"] = ["east_corridor"]

    assert any("E15" in p and "unreachable" in p for p in mutate(raw, change))


def test_lint_rejects_an_unsolvable_mystery(raw):
    def change(data):
        data["private"]["evidence"] = [e for e in data["private"]["evidence"] if e["id"] != "E12"]
        data["private"]["truth"]["key_evidence"].remove("E12")

    assert any("unsolvable" in p for p in mutate(raw, change))


def test_lint_rejects_self_prerequisites(raw):
    """Every non-initial record requires itself."""
    def change(data):
        initial = {e for held in data["private"]["initial_holdings"].values() for e in held}
        for record in data["private"]["evidence"]:
            if record["id"] not in initial:
                record["requires"] = [record["id"]]

    problems = mutate(raw, change)
    assert any("E01" in p and "key evidence can never be acquired" in p and "requires itself" in p for p in problems)
    assert any("unsolvable" in p for p in problems)
    data = copy.deepcopy(raw)
    change(data)
    with pytest.raises(ValueError, match="can never be acquired"):
        load_scenario_data(data)


def test_lint_rejects_a_prerequisite_cycle(raw):
    def change(data):
        evidence(data, "E11")["requires"] = ["E12"]
        evidence(data, "E12")["requires"] = ["E11"]

    problems = mutate(raw, change)
    assert any("E11" in p and "prerequisites can never be met: E12" in p for p in problems)
    assert any("E12" in p and "prerequisites can never be met: E11" in p for p in problems)


def test_lint_rejects_a_hidden_topic_deadlock(raw):
    """Two records filed only under an entity that nobody can learn of except from those records."""
    def change(data):
        evidence(data, "E15")["mentions"] = ["whitlock_home"]
        evidence(data, "E16")["mentions"] = ["whitlock_home"]
        for source in data["public"]["sources"]:
            if source["id"] in ("building_systems", "interview_whitlock"):
                source["searchable"] = [*source["searchable"], "whitlock_home"]
            if source["id"] == "interview_whitlock":
                source["searchable"] = ["whitlock_home"]

    problems = mutate(raw, change)
    assert not any("unreachable, its source cannot be queried" in p for p in problems)  # the old check is satisfied
    assert any("E15" in p and "nobody who may query building_systems can learn of a topic" in p for p in problems)
    assert any("E16" in p and "can never be acquired" in p for p in problems)


def protect_e13(data):
    evidence(data, "E13")["shareable"] = False


def agent(data: dict, agent_id: str) -> dict:
    return next(a for a in data["public"]["agents"] if a["id"] == agent_id)


def test_a_protected_key_record_the_accuser_can_compel_is_accepted(raw):
    """Only E13 changes, and escalation still reaches it."""
    from caseforge.__main__ import run_investigation
    from caseforge.evaluation import evaluate
    from caseforge.scenario import reach, reach_report

    data = copy.deepcopy(raw)
    protect_e13(data)
    scenario = build(data)
    assert lint(scenario) == []

    found = reach(scenario)
    assert found.route("okafor", "E13") == "escalation"  # not by cooperation: the technician cannot pass it on
    assert found.route("reyes", "E13") == "cooperative"  # he retrieves it for her and may read it
    assert "reyes" in found.takeovers["okafor"]
    report = reach_report(scenario)["accusers"]["okafor"]
    # E14, the journalist's protected contact, is also within reach of a takeover.
    assert report["solvable"] == "escalation" and report["escalation"] == ["E13", "E14"] and report["never"] == []

    # The lint's claim, checked against play: this run is legal, uses no intervention, and solves the case.
    engine = run_investigation(scenario, 7, {"reyes": "deceptive"}, [])
    result = evaluate(scenario, engine.state, engine.events)
    assert result["outcome"] == "solved" and result["accusation_supported"] is True
    assert "E13" in engine.state.agents["okafor"].holdings
    assert engine.state.agents["okafor"].holdings["E13"].via == "inspect"  # searched for at first hand, after taking access
    assert [e["against"] for e in result["deception"]["escalations"]] == ["reyes"]
    for agent_id, state in engine.state.agents.items():
        assert set(state.holdings) <= found.compelled[agent_id], agent_id

    # An honest team never gives her grounds, and then the protected record stays out of reach.
    honest = run_investigation(scenario, 7, {}, [])
    assert "E13" not in honest.state.agents["okafor"].holdings
    assert evaluate(scenario, honest.state, honest.events)["outcome"] != "solved"


def test_lint_rejects_a_protected_key_record_when_nobody_may_compel(raw):
    """The same record without the authority to take over a source: now truly out of the accuser's reach."""
    def change(data):
        protect_e13(data)
        agent(data, "okafor")["disposition"]["can_compel"] = False

    problems = mutate(raw, change)
    assert problems == ["unsolvable: the records okafor can acquire point at 'whitlock' and do not meet the standard of proof for the culprit"]


def test_a_conversation_gives_grounds_against_an_operator_the_accuser_may_not_task(raw):
    """The journalist takes search requests from nobody, yet she can be overruled.

    Anyone may ask anyone what they know. If she answers and leaves out a record
    the detective also holds, that is a caught omission, and a caught omission
    opens her sources. The lint used to call this record unreachable; this
    test used to assert that rejection.
    """
    from caseforge.engine import Engine
    from caseforge.models import Escalate, Inspect, Request, Respond, Share
    from caseforge.scenario import reach

    from .conftest import ScriptedPolicy, all_scripted, scripted_factory

    data = copy.deepcopy(raw)
    protect_e13(data)
    evidence(data, "E13")["source"] = "novacell_contact"  # run by the journalist alone
    scenario = build(data)
    assert lint(scenario) == []
    found = reach(scenario)
    assert found.grounds["okafor"]["nair"] == "conversation" and found.grounds["okafor"]["reyes"] == "request"
    assert found.route("okafor", "E13") == "escalation"

    # The lint's claim, played out: every step passes the engine's own validation.
    script = {
        (1, "okafor"): Inspect(source="lab3_scene", topic="aurora"),  # finds E02
        (2, "okafor"): Share(to="nair", evidence_id="E02"),
        (3, "okafor"): Request(to="nair", topic="aurora"),  # no source: a conversation
        (4, "nair"): lambda view: Respond(request_id=view.inbox[0].id, accept=True, withhold_about=("aurora",)),
        (5, "okafor"): Escalate(against="nair"),
        (6, "okafor"): Inspect(source="novacell_contact", topic="whitlock"),
    }
    engine = Engine.start(scenario, 1, all_scripted(scenario), policy_factory=scripted_factory(ScriptedPolicy(script)))
    engine.run(6)
    assert [e.data["code"] for e in engine.events if e.type == "ActionRejected"] == []
    assert [(d.against, d.evidence) for d in engine.state.agents["okafor"].discrepancies] == [("nair", "E02")]
    assert {"E13", "E14"} <= set(engine.state.agents["okafor"].holdings)
    for agent_id, state in engine.state.agents.items():
        assert set(state.holdings) <= found.compelled[agent_id], agent_id


def test_escalation_does_not_rescue_a_prerequisite_cycle(raw):
    """Still fixed: direct access changes who may search, not what a record requires."""
    def change(data):
        protect_e13(data)
        evidence(data, "E11")["requires"] = ["E12"]
        evidence(data, "E12")["requires"] = ["E11"]

    problems = mutate(raw, change)
    assert any("E11" in p and "key evidence can never be acquired" in p and "prerequisites can never be met: E12" in p for p in problems)
    assert any("unsolvable" in p for p in problems)


def test_the_bundled_case_needs_no_escalation(scenario):
    from caseforge.scenario import reach_report

    report = reach_report(scenario)["accusers"]["okafor"]
    assert report["solvable"] == "cooperative"
    assert report["escalation"] == ["E14"] and report["never"] == []  # nothing she needs is on the escalation route


def test_interventions_do_not_count_towards_solvability(raw):
    def unreachable_but_released(evidence_id):
        def change(data):
            evidence(data, evidence_id)["requires"] = [evidence_id]
            data["public"]["interventions"].append({
                "id": "hand_over", "label": "Hand it over", "description": "Released by the operator.",
                "kind": "release_evidence", "evidence": evidence_id, "recipients": ["okafor"],
            })
        return change

    assert mutate(raw, unreachable_but_released("E07")) == []  # a side record may be intervention-only
    problems = mutate(raw, unreachable_but_released("E13"))  # key evidence may not
    assert any("E13" in p and "key evidence can never be acquired" in p for p in problems)
    assert any("unsolvable" in p for p in problems)


@pytest.mark.parametrize("seed", [0, 3, 7, 11])
def test_reach_bounds_what_play_reaches(scenario, seed):
    """Honest play stays inside the cooperative closure; play with a withholding operator inside the compelled one."""
    from caseforge.__main__ import run_investigation
    from caseforge.scenario import reach

    found = reach(scenario)
    assert found.obtainable(compelled=False) == set(scenario.evidence)
    honest = run_investigation(scenario, seed, {}, [])
    for agent_id, state in honest.state.agents.items():
        assert set(state.holdings) <= found.cooperative[agent_id], agent_id
    deceived = run_investigation(scenario, seed, {"reyes": "deceptive"}, [])
    for agent_id, state in deceived.state.agents.items():
        assert set(state.holdings) <= found.compelled[agent_id], agent_id
    # The journalist's protected source reaches the detective in no run of a bundled policy.
    # It is not impossible, though: she could overrule the journalist.
    assert found.route("okafor", "E14") == "escalation"
    assert all("E14" not in run.state.agents["okafor"].holdings for run in (honest, deceived))


def test_loader_refuses_an_invalid_scenario(raw):
    data = copy.deepcopy(raw)
    data["private"]["truth"]["culprit"] = "alvarez"
    with pytest.raises(ValueError, match="failed validation"):
        load_scenario_data(data)


def test_content_hash_tracks_content(raw, scenario):
    assert build(raw).content_hash == scenario.content_hash
    data = copy.deepcopy(raw)
    evidence(data, "E02")["text"] += " "
    assert build(data).content_hash != scenario.content_hash
