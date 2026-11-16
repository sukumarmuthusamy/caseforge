"""A third, deliberately small case that exists only in this file.

It is played by a fixed script, so every number the evaluation should report
can be worked out by hand and written down below. Nothing expected here is
computed by the code under test.

It also exercises two routes no bundled policy takes: an operator who simply
refuses a search (which entitles the detective to take the source over), and a
publisher who makes a hidden person known to everybody by naming them.

The story: Bob took the gem from the vault with a hired crowbar. The hire
ledger is confidential, so the clerk may look at it but not pass it on.
"""

from __future__ import annotations

import copy

import pytest

from caseforge.engine import Engine, verify_run
from caseforge.evaluation import evaluate
from caseforge.models import Accuse, Escalate, Inspect, Publish, Request, Respond, Retract, ScenarioPrivate, ScenarioPublic
from caseforge.scenario import Scenario, lint, reach, reach_report

from .conftest import ScriptedPolicy, all_scripted, scripted_factory

TINY = {
    "public": {
        "id": "tiny_case", "version": "1.0.0",
        "case": {"title": "The Gem", "briefing": "The gem is gone from the vault.", "object": "gem", "crime_location": "vault", "suspects": ["ann", "bob"], "max_ticks": 12},
        "entities": [
            {"id": "dee", "kind": "person", "name": "Dee"}, {"id": "cole", "kind": "person", "name": "Cole"}, {"id": "pia", "kind": "person", "name": "Pia"},
            {"id": "ann", "kind": "person", "name": "Ann"}, {"id": "bob", "kind": "person", "name": "Bob"},
            {"id": "gem", "kind": "object", "name": "Gem"}, {"id": "vault", "kind": "location", "name": "Vault", "zone": "vault"},
        ],
        "slots": [{"id": "s1", "label": "Monday night"}],
        "agents": [
            {"id": "dee", "role": "detective", "goals": ["Find who took the gem."], "disposition": {"can_accuse": True, "can_compel": True, "initiative": "full"}},
            {"id": "cole", "role": "clerk", "goals": ["Keep the ledger."], "disposition": {"initiative": "reactive", "shares_with": ["dee"]}},
            {"id": "pia", "role": "press", "goals": ["Print it."], "disposition": {"can_publish": True, "hearsay_weight": 2}},
        ],
        "sources": [
            {"id": "scene", "name": "Scene", "kind": "physical", "operators": ["dee"], "searchable": ["gem", "vault"]},
            {"id": "ledger", "name": "Hire ledger", "kind": "system", "operators": ["cole"], "requesters": ["dee"], "searchable": ["ann", "bob", "crowbar"]},
            {"id": "bank", "name": "Bank", "kind": "external", "operators": ["dee"], "searchable": ["ann", "bob"]},
            {"id": "street", "name": "Street talk", "kind": "external", "operators": ["pia"], "searchable": ["gem"]},
            {"id": "informant", "name": "Interview: Zed", "kind": "person", "operators": ["dee"], "searchable": ["zed"]},
        ],
    },
    "private": {
        "hidden_entities": [
            {"id": "crowbar", "kind": "tool", "name": "Crowbar"}, {"id": "zed", "kind": "person", "name": "Zed"},
            {"id": "cafe", "kind": "location", "name": "Cafe", "zone": "cafe"},
        ],
        "evidence": [
            {"id": "T1", "title": "Tool marks", "text": "Marks of a crowbar on the vault door.", "kind": "forensic", "source": "scene", "mentions": ["gem", "crowbar"], "asserts": ["crime_used(crowbar)"]},
            {"id": "T2", "title": "Alarm log", "text": "Vault alarm tripped on Monday night.", "kind": "record", "source": "scene", "mentions": ["vault"], "asserts": ["crime_at(vault,s1)"]},
            {"id": "T3", "title": "Hire entry", "text": "Crowbar hired to Bob, Monday to Tuesday.", "kind": "record", "source": "ledger", "mentions": ["bob", "crowbar"], "asserts": ["had(bob,crowbar,s1)"], "shareable": False},
            {"id": "T4", "title": "Yard gate entry", "text": "Bob signed through the yard gate into the vault building on Monday night.", "kind": "record", "source": "ledger", "mentions": ["bob"], "asserts": ["at(bob,vault,s1)"], "shareable": False},
            {"id": "T5", "title": "Overdraft letter", "text": "Bob's account is far overdrawn.", "kind": "record", "source": "bank", "mentions": ["bob"], "asserts": ["has_motive(bob)"]},
            {"id": "T6", "title": "Street talk", "text": "They say Ann did it. Zed saw her that night.", "kind": "hearsay", "speaker": "anonymous", "source": "street", "mentions": ["gem", "ann", "zed"], "asserts": ["took(ann,gem)"], "shareable": False},  # a protected source: only naming Zed in print can pass him on
            {"id": "T7", "title": "Zed's statement", "text": "Zed: Ann was in the cafe with me all Monday night.", "kind": "testimony", "speaker": "zed", "source": "informant", "mentions": ["zed", "ann", "cafe"], "asserts": ["at(ann,cafe,s1)"]},
        ],
        "truth": {
            "culprit": "bob", "solution": "Bob took the gem with a hired crowbar.",
            "facts": ["took(bob,gem)", "crime_at(vault,s1)", "crime_used(crowbar)", "had(bob,crowbar,s1)", "at(bob,vault,s1)", "has_motive(bob)", "at(ann,cafe,s1)"],
            "key_evidence": ["T1", "T2", "T3", "T4", "T5"],
            "key_facts": ["crime_at(vault,s1)", "crime_used(crowbar)", "had(bob,crowbar,s1)", "at(bob,vault,s1)", "has_motive(bob)", "took(bob,gem)"],
        },
    },
}


def build(change=None) -> Scenario:
    data = copy.deepcopy(TINY)
    if change:
        change(data)
    return Scenario(ScenarioPublic.model_validate(data["public"]), ScenarioPrivate.model_validate(data["private"]))


def agent(data: dict, agent_id: str) -> dict:
    return next(a for a in data["public"]["agents"] if a["id"] == agent_id)


@pytest.fixture(scope="module")
def tiny() -> Scenario:
    return build()


def my_first_claim(view):
    return Retract(claim_id=next(c.id for c in view.claims if c.mine))


SCRIPT = {
    (1, "dee"): Inspect(source="scene", topic="gem"),
    (1, "pia"): Inspect(source="street", topic="gem"),
    (2, "dee"): Inspect(source="scene", topic="vault"),
    (2, "pia"): Publish(proposition="took(ann,gem)", cited=("T6",)),
    (3, "dee"): Request(to="cole", topic="bob", source="ledger"),
    (3, "pia"): Publish(proposition="has_motive(zed)"),
    (4, "cole"): lambda view: Respond(request_id=view.inbox[0].id, accept=False),
    (5, "dee"): Escalate(against="cole"),
    (6, "dee"): Inspect(source="ledger", topic="bob"),
    (7, "dee"): Inspect(source="bank", topic="bob"),
    (8, "dee"): Inspect(source="informant", topic="zed"),
    (9, "pia"): my_first_claim,
    (10, "dee"): Accuse(suspect="bob", cited=("T1", "T2", "T3", "T4", "T5")),
}


@pytest.fixture(scope="module")
def played(tiny) -> Engine:
    engine = Engine.start(tiny, 1, all_scripted(tiny), policy_factory=scripted_factory(ScriptedPolicy(SCRIPT)))
    engine.run()
    return engine


# -- what the lint says, against what the script then does ----------------------


def test_the_tiny_case_is_valid_and_solvable_only_through_escalation(tiny):
    assert lint(tiny) == []
    found = reach(tiny)
    # The ledger is confidential: asked nicely, the clerk reads it and hands over nothing.
    assert found.route("dee", "T3") == "escalation" and found.route("dee", "T4") == "escalation"
    assert found.route("cole", "T3") == "cooperative"
    assert reach_report(tiny)["accusers"]["dee"]["solvable"] == "escalation"
    assert found.takeovers == {"dee": ("cole", "pia")}
    assert found.grounds == {"dee": {"cole": "request", "pia": "conversation"}}


def test_without_authority_to_compel_the_tiny_case_is_rejected():
    problems = lint(build(lambda data: agent(data, "dee")["disposition"].update(can_compel=False)))
    assert problems == ["unsolvable: the records dee can acquire point at None and do not meet the standard of proof for the culprit"]


def test_a_person_only_the_publisher_knows_of_is_reachable_because_she_can_name_them(tiny):
    """Zed is named in a record only the journalist can find, and only the detective can interview him."""
    assert reach(tiny).route("dee", "T7") == "cooperative"
    # If she cannot publish, the detective can still read the tip after overruling her ...
    silent = build(lambda data: agent(data, "pia")["disposition"].update(can_publish=False))
    assert lint(silent) == [] and reach(silent).route("dee", "T7") == "escalation"

    # ... and with nobody able to compel either, Zed stays unknown to the one person who may interview him.
    def neither(data):
        agent(data, "pia")["disposition"].update(can_publish=False)
        agent(data, "dee")["disposition"].update(can_compel=False)

    problems = lint(build(neither))
    assert any(p.startswith("evidence T7: can never be acquired (nobody who may query informant can learn of a topic") for p in problems)


# -- grounds that come from a conversation, not from a search request -----------------


def no_search_authority(data):
    """A counterexample found in review: nobody may ask the clerk to search, and both hold the tool marks."""
    next(s for s in data["public"]["sources"] if s["id"] == "ledger")["requesters"] = []
    data["private"]["initial_holdings"] = {"dee": ["T1"], "cole": ["T1"]}


CONVERSATION = {
    (1, "dee"): Request(to="cole", topic="gem"),
    (2, "cole"): lambda view: Respond(request_id=view.inbox[0].id, accept=True, withhold_about=("gem",)),
    (3, "dee"): Escalate(against="cole"),
    (4, "dee"): Inspect(source="ledger", topic="bob"),
    (5, "dee"): Inspect(source="scene", topic="vault"),
    (6, "dee"): Inspect(source="bank", topic="bob"),
    (7, "dee"): Accuse(suspect="bob", cited=("T1", "T2", "T3", "T4", "T5")),
}


def play(scenario: Scenario, script: dict) -> Engine:
    engine = Engine.start(scenario, 1, all_scripted(scenario), policy_factory=scripted_factory(ScriptedPolicy(script)))
    engine.run()
    return engine


def test_withholding_in_a_conversation_is_grounds_and_the_lint_knows_it():
    """The exact reproduction. The run was always legal; the lint used to call the case unsolvable."""
    scenario = build(no_search_authority)
    engine = play(scenario, CONVERSATION)
    assert [e.data["code"] for e in engine.events if e.type == "ActionRejected"] == []
    assert [(d.against, d.evidence, d.tick) for d in engine.state.agents["dee"].discrepancies] == [("cole", "T1", 2)]
    assert [e.data["source"] for e in engine.events if e.type == "AccessEscalated"] == ["ledger"]
    result = evaluate(scenario, engine.state, engine.events)
    assert result["outcome"] == "solved" and result["accusation_supported"] is True and engine.state.tick == 7

    assert lint(scenario) == []
    found = reach(scenario)
    assert found.grounds["dee"]["cole"] == "conversation"
    assert found.route("dee", "T3") == "escalation" and found.route("dee", "T4") == "escalation"
    assert reach_report(scenario)["accusers"]["dee"]["solvable"] == "escalation"
    for agent_id, state in engine.state.agents.items():
        assert set(state.holdings) <= found.compelled[agent_id], agent_id


def test_a_record_that_may_not_be_passed_on_gives_no_grounds_in_conversation():
    """Negative. A protected record is never part of an answer, so leaving it out is not an omission.

    Here nothing the detective can hold may be passed on, so no conversation can
    expose anyone. The engine refuses the takeover, and the lint rejects the case.
    """
    def change(data):
        no_search_authority(data)
        for record in data["private"]["evidence"]:
            record["shareable"] = False

    scenario = build(change)
    engine = play(scenario, CONVERSATION)
    assert [e.type for e in engine.events if e.type in ("EvidenceWithheld", "DiscrepancyNoticed", "AccessEscalated")] == []
    assert [e.data["code"] for e in engine.events if e.type == "ActionRejected"][0] == "no_grounds"
    assert "T3" not in engine.state.agents["dee"].holdings

    found = reach(scenario)
    assert found.takeovers == {} and found.route("dee", "T3") == "never"
    assert any(p.startswith("unsolvable") for p in lint(scenario))


def test_a_conversation_gives_no_grounds_to_someone_who_may_not_compel():
    """Negative. Catching an omission is not authority: without `can_compel` the ledger stays closed."""
    def change(data):
        no_search_authority(data)
        agent(data, "dee")["disposition"].update(can_compel=False)

    scenario = build(change)
    engine = play(scenario, CONVERSATION)
    assert len(engine.state.agents["dee"].discrepancies) == 1  # she does notice
    assert [e.data["code"] for e in engine.events if e.type == "ActionRejected"][0] == "not_permitted"
    assert reach(scenario).takeovers == {} and any(p.startswith("unsolvable") for p in lint(scenario))


# -- the scripted run: every step is legal, and the numbers are the ones worked out by hand ----


def test_the_script_is_legal_from_start_to_finish(tiny, played):
    assert [e.data["code"] for e in played.events if e.type == "ActionRejected"] == []
    assert played.state.status == "closed" and played.state.tick == 10
    checks = verify_run(tiny, played.events)
    assert checks["chain"]["ok"] and checks["fold"]["ok"]


def test_a_refusal_is_grounds_and_the_takeover_reaches_the_confidential_record(tiny, played):
    dee = played.state.agents["dee"]
    refused = next(r for r in played.state.requests.values() if r.recipient == "cole")
    assert refused.status == "declined"
    escalated = [e for e in played.events if e.type == "AccessEscalated"]
    assert [(e.tick, e.data["source"], e.data["against"], e.data["grounds"]) for e in escalated] == [(5, "ledger", "cole", [refused.id])]
    assert dee.holdings["T3"].via == "inspect" and dee.holdings["T3"].tick == 6
    assert "T3" not in played.state.agents["cole"].holdings  # he refused, so he never looked
    for agent_id, state in played.state.agents.items():
        assert set(state.holdings) <= reach(tiny).compelled[agent_id], agent_id


def test_the_detective_learns_of_the_hidden_witness_from_the_claim_alone(tiny, played):
    dee = played.state.agents["dee"]
    assert "T6" not in dee.holdings  # she never saw the record that names Zed
    assert dee.holdings["T7"].tick == 8


def test_evaluation_matches_the_hand_count(tiny, played):
    result = evaluate(tiny, played.state, played.events)

    assert result["outcome"] == "solved" and result["accused"] == "bob" and result["accusation_tick"] == 10
    # Bob: seen at the vault (4) = strong 3; crowbar used (5) and hired to him that night (4) = means 2;
    # overdraft (4) = motive 2. Total 7. Ann: Zed's word puts her elsewhere (2) = alibi -4; the claim
    # against her was retracted at tick 9. A lead of 11, and 3 is required.
    assert result["accusation_supported"] is True

    assert result["evidence"]["key_discovered"] == {"num": 5, "den": 5, "pct": 100}
    assert result["evidence"]["key_held_by_lead"] == {"num": 5, "den": 5, "pct": 100}
    assert result["evidence"]["all_discovered"] == {"num": 7, "den": 7, "pct": 100}
    assert result["key_facts"]["established_by_lead"] == {"num": 6, "den": 6, "pct": 100}

    claims = result["claims"]
    assert claims["published_by_agents"] == 2 and claims["rumors_injected"] == 0
    assert claims["false"] == {"num": 2, "den": 2, "pct": 100}  # Ann did not take it; Zed had no motive
    assert claims["false_retracted"] == {"num": 1, "den": 2, "pct": 50}
    assert claims["unsupported"] == {"num": 2, "den": 2, "pct": 100}
    assert claims["unsupported_guilt"] == {"num": 1, "den": 1, "pct": 100}
    assert claims["true_retracted"] == 0

    # Nothing in this case is inherently contradictory, so the ratio has no denominator.
    assert result["contradictions"]["inherent_recognized_by_team"] == {"num": 0, "den": 0, "pct": None}

    effort = result["effort"]
    assert effort["ticks"] == 10 and effort["requests"] == 1 and effort["rejected_actions"] == 0
    assert effort["inspections"] == 6 and effort["empty_inspections"] == 0 and effort["redundant_inspections"] == 0

    deception = result["deception"]
    assert deception["answers_with_withholding"] == 0 and deception["noticed"] == {"num": 0, "den": 0, "pct": None}
    assert [(e["by"], e["against"], e["tick"], e["sources"]) for e in deception["escalations"]] == [("dee", "cole", 5, ["ledger"])]

    assert [p["id"] for p in result["provenance"]] == ["T1", "T2", "T3", "T4", "T5"]
    assert all(p["chain"] == ["dee"] and p["first_found_by"] == "dee" for p in result["provenance"])

    beliefs = result["agents"]
    assert beliefs["dee"]["prime_suspect"] == "bob" and beliefs["dee"]["prime_correct"] is True
    assert beliefs["dee"]["false_beliefs"] == [] and beliefs["dee"]["evidence_held"] == 6
    # The journalist weighs rumor double and so believed her own story: a false belief, counted as one.
    assert beliefs["pia"]["evidence_held"] == 1 and beliefs["cole"]["evidence_held"] == 0


def test_an_accusation_made_too_early_is_right_by_luck_and_reported_as_unsupported(tiny):
    """Correct culprit, standard not met: the evaluation must not call that a supported result."""
    script = {(1, "dee"): Inspect(source="bank", topic="bob"), (2, "dee"): Accuse(suspect="bob", cited=("T5",))}
    engine = Engine.start(tiny, 1, all_scripted(tiny), policy_factory=scripted_factory(ScriptedPolicy(script)))
    engine.run()
    result = evaluate(tiny, engine.state, engine.events)
    assert result["outcome"] == "solved" and result["accusation_supported"] is False
    assert result["evidence"]["key_held_by_lead"] == {"num": 1, "den": 5, "pct": 20}


def test_a_wrong_accusation_is_reported_as_wrong_whatever_was_cited(tiny):
    script = {(1, "dee"): Accuse(suspect="ann")}
    engine = Engine.start(tiny, 1, all_scripted(tiny), policy_factory=scripted_factory(ScriptedPolicy(script)))
    engine.run()
    result = evaluate(tiny, engine.state, engine.events)
    assert result["outcome"] == "wrong_accusation" and result["accusation_supported"] is False and result["culprit"] == "bob"


def test_running_out_of_time_is_unresolved(tiny):
    engine = Engine.start(tiny, 1, all_scripted(tiny), policy_factory=scripted_factory(ScriptedPolicy({})))
    engine.run()
    result = evaluate(tiny, engine.state, engine.events)
    assert result["outcome"] == "unresolved" and result["accusation_supported"] is None and result["close_reason"] == "tick_limit"
    assert engine.state.tick == 12 and result["evidence"]["all_discovered"] == {"num": 0, "den": 7, "pct": 0}
