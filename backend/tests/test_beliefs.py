"""Belief revision: evidence changes beliefs, rumors do not become facts, and the reason is recorded."""

from __future__ import annotations

from caseforge.__main__ import run_investigation
from caseforge.models import Proposition
from caseforge.reasoning import Item, meets_standard, revise

BRANDT_AT_LAB = "at(brandt,lab3,oct14_2145)"
BRANDT_AT_DINNER = "at(brandt,osteria,oct14_2145)"


def reason(scenario, ids, hearsay_weight=1, extra=()):
    items = [scenario.item_for(i) for i in ids] + list(extra)
    return revise(items, scenario.reasoning_context(hearsay_weight))


def test_door_log_alone_points_at_the_card_holder(scenario):
    r = reason(scenario, ["E01"])
    assert r.beliefs[BRANDT_AT_LAB].status == "believed"
    assert [d.rule for d in r.beliefs[BRANDT_AT_LAB].derivations] == ["R1"]
    assert r.prime_suspect == "brandt"
    assert r.suspects["brandt"].opportunity == "strong" and r.suspects["brandt"].means


def test_new_evidence_contradicts_and_overturns_a_belief(scenario):
    before = reason(scenario, ["E01"])
    after = reason(scenario, ["E01", "E03"])
    assert before.beliefs[BRANDT_AT_LAB].status == "believed"
    assert after.beliefs[BRANDT_AT_LAB].status == "rejected"
    assert after.beliefs[BRANDT_AT_LAB].against == ("E03",)
    assert after.beliefs[BRANDT_AT_DINNER].status == "believed"
    assert after.suspects["brandt"].opportunity == "alibi"
    assert f"{BRANDT_AT_LAB}|{BRANDT_AT_DINNER}" in after.contradictions
    assert after.prime_suspect != "brandt"


def test_forensics_defeats_the_inference_instead_of_just_outweighing_it(scenario):
    r = reason(scenario, ["E01", "E03", "E10"])
    (derivation,) = r.beliefs[BRANDT_AT_LAB].derivations
    assert derivation.active is False and derivation.defeated_by == "card_cloned(card0417)"
    assert r.beliefs[BRANDT_AT_LAB].support == 0
    assert r.contradictions == []  # nothing left to contradict
    assert not r.suspects["brandt"].means  # a cloned card no longer implicates its holder


def test_a_rumor_never_becomes_a_belief(scenario):
    r = reason(scenario, ["E06"])
    assert r.beliefs["took(brandt,aurora)"].status == "tentative"
    assert r.suspects["brandt"].named == 1 and r.prime_suspect is None
    assert not meets_standard(r.suspects, "brandt")


def test_repeated_hearsay_does_not_stack(scenario):
    accusation = Proposition.parse("took(mercer,aurora)")
    one = [Item(id="C1", kind="hearsay", speaker="anonymous", asserts=(accusation,))]
    many = [Item(id=f"C{i}", kind="hearsay", speaker=f"voice{i}", asserts=(accusation,)) for i in range(10)]
    assert reason(scenario, [], extra=one).suspects["mercer"] == reason(scenario, [], extra=many).suspects["mercer"]


def test_agreement_between_speakers_cannot_meet_the_standard(scenario):
    """However many agents repeat it, an allegation satisfies no leg of the standard."""
    claims = [
        Item(id=f"C{i}", kind="hearsay", speaker=speaker, asserts=(Proposition.parse(p),))
        for i, (speaker, p) in enumerate([
            ("nair", "took(mercer,aurora)"), ("brandt", "took(mercer,aurora)"),
            ("reyes", "took(mercer,aurora)"), ("nair", "has_motive(mercer)"),
        ])
    ]
    r = reason(scenario, ["E01", "E04"], extra=claims)
    assert r.suspects["mercer"].motive == "weak"
    assert not meets_standard(r.suspects, "mercer")
    assert r.beliefs["took(mercer,aurora)"].status != "believed"


def test_a_record_outweighs_a_witness(scenario):
    r = reason(scenario, ["E01", "E04", "E05"])
    assert r.beliefs["at(mercer,east_corridor,oct14_2145)"].status == "rejected"
    assert r.beliefs["at(mercer,rooftop,oct14_2145)"].status == "believed"
    assert r.suspects["mercer"].opportunity == "alibi"


def test_a_suspects_own_word_is_not_an_alibi(scenario):
    r = reason(scenario, ["E01", "E16"])
    assert r.suspects["whitlock"].opportunity == "none"
    assert r.beliefs["at(whitlock,whitlock_home,oct14_2145)"].status == "tentative"


def test_clone_chain_derives_means_and_presence(scenario):
    r = reason(scenario, ["E01", "E11", "E12"])
    assert r.beliefs["card_cloned(card0417)"].status == "believed"
    assert r.beliefs["could_use(whitlock,card0417)"].derivations[0].rule == "R3"
    assert [d.rule for d in r.beliefs["at(whitlock,lab3,oct14_2145)"].derivations] == ["R4"]
    assert r.suspects["whitlock"].means and r.suspects["whitlock"].opportunity == "strong"


def test_standard_of_proof_needs_a_believed_motive(scenario):
    chain = ["E01", "E11", "E12", "E15"]
    hearsay_only = reason(scenario, chain + ["E14"])
    assert hearsay_only.suspects["whitlock"].motive == "weak"
    assert not meets_standard(hearsay_only.suspects, "whitlock")
    assert meets_standard(reason(scenario, chain + ["E13"]).suspects, "whitlock")


def test_disposition_changes_what_the_same_evidence_means(scenario):
    neutral = reason(scenario, ["E14"], hearsay_weight=1)
    credulous = reason(scenario, ["E14"], hearsay_weight=2)
    assert neutral.beliefs["has_motive(whitlock)"].status == "tentative"
    assert credulous.beliefs["has_motive(whitlock)"].status == "believed"


def test_revision_is_order_independent(scenario):
    ids = sorted(scenario.evidence)
    forward = reason(scenario, ids)
    backward = reason(scenario, list(reversed(ids)))
    assert forward.beliefs == backward.beliefs and forward.suspects == backward.suspects


def test_the_run_records_why_the_detective_changed_her_mind(solved):
    """Find the recorded moment Okafor's belief about Brandt flipped and check its stated cause."""
    flips = [
        e for e in solved.events
        if e.type == "BeliefsRevised" and e.data["agent"] == "okafor"
        and (e.data["changes"].get(BRANDT_AT_LAB) or {}).get("status") == "rejected"
    ]
    assert flips, "expected Okafor to reject 'Brandt was in the lab' at some point"
    flip = flips[0]
    assert flip.data["because"] == ["E03"]
    assert flip.data["prime_before"] == "brandt" and flip.data["prime_after"] != "brandt"
    cause = solved.events[flip.cause]
    assert cause.type == "ActionTaken"
    earlier = [e for e in solved.events[: flip.seq] if e.type == "BeliefsRevised" and e.data["agent"] == "okafor" and BRANDT_AT_LAB in e.data["changes"]]
    assert earlier[-1].data["changes"][BRANDT_AT_LAB]["status"] == "believed"


def test_injected_rumor_changes_nobodys_truth(scenario):
    engine = run_investigation(scenario, 7, {}, [(0, "rumor_contractor")])
    rumor = next(c for c in engine.state.claims.values() if c.by == "anonymous")
    assert rumor.proposition == "took(mercer,aurora)"
    assert scenario.truth.culprit == "whitlock"
    assert scenario.truth_value(Proposition.parse(rumor.proposition)) is False
    # Everyone heard it; nobody ended up believing it.
    for agent in engine.state.agents.values():
        assert rumor.id in agent.heard
        assert agent.beliefs["took(mercer,aurora)"].status != "believed"
    assert engine.state.accusation["suspect"] == "whitlock"


def test_hearsay_only_motive_convinces_a_credulous_agent_but_never_the_reference_standard(scenario):
    """Personal conviction depends on the agent's weights; the reference standard does not."""
    ids = ["E01", "E10", "E11", "E12", "E14", "E15"]  # everything but the recruiter's email; E14 is hearsay
    items = [scenario.item_for(e) for e in ids]
    neutral = revise(items, scenario.reasoning_context(1))
    credulous = revise(items, scenario.reasoning_context(2))
    assert neutral.suspects["whitlock"].motive == "weak" and not meets_standard(neutral.suspects, "whitlock")
    assert credulous.suspects["whitlock"].motive == "strong" and meets_standard(credulous.suspects, "whitlock")
    # Evaluation judges every claim and accusation with the neutral weights.
    import ast
    import inspect

    import caseforge.evaluation as evaluation

    calls = [n for n in ast.walk(ast.parse(inspect.getsource(evaluation))) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "reasoning_context"]
    assert calls and all(len(c.args) == 1 and isinstance(c.args[0], ast.Constant) and c.args[0].value == 1 for c in calls)
