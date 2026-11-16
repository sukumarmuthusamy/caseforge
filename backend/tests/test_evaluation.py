"""Evaluation: objective outcomes with explicit denominators."""

from __future__ import annotations

from caseforge.__main__ import run_investigation
from caseforge.engine import Engine
from caseforge.evaluation import evaluate, progress, ratio
from caseforge.models import Accuse, Inspect, Proposition, Publish

from .conftest import SEED, ScriptedPolicy, all_scripted, scripted_factory


def scripted_run(scenario, script):
    engine = Engine.start(scenario, SEED, all_scripted(scenario), scripted_factory(ScriptedPolicy(script)))
    engine.run()
    return engine, evaluate(scenario, engine.state, engine.events)


def test_ratio_has_no_value_without_a_denominator():
    assert ratio(0, 0) == {"num": 0, "den": 0, "pct": None}
    assert ratio(1, 4) == {"num": 1, "den": 4, "pct": 25}


def test_baseline_run_is_scored_as_solved_and_supported(scenario, solved):
    result = evaluate(scenario, solved.state, solved.events)
    assert result["outcome"] == "solved"
    assert result["accused"] == result["culprit"] == "whitlock"
    assert result["accusation_supported"] is True
    assert result["evidence"]["key_discovered"] == ratio(6, 6)
    assert result["evidence"]["key_held_by_lead"]["num"] == 6
    assert result["evidence"]["all_discovered"]["den"] == len(scenario.evidence)
    assert result["key_facts"]["established_by_lead"]["num"] == result["key_facts"]["established_by_lead"]["den"]
    assert result["contradictions"]["resolved_correctly_by_lead"]["pct"] == 100
    cited = {p["id"] for p in result["provenance"]}
    assert cited == set(solved.state.accusation["cited"]) and cited <= set(solved.state.agents["okafor"].holdings)
    for row in result["provenance"]:
        assert row["chain"][-1] == "okafor" and row["first_found_by"] in scenario.agents


def test_false_public_claim_is_flagged_and_its_retraction_counted(scenario, solved):
    claims = evaluate(scenario, solved.state, solved.events)["claims"]
    false = [c for c in claims["items"] if c["true"] is False]
    assert false and all(c["by"] == "nair" and not c["supported"] for c in false)
    assert claims["false"]["num"] == len(false)
    assert claims["false_retracted"] == ratio(sum(c["retracted"] for c in false), len(false))
    assert claims["unsupported_guilt"]["den"] == sum(1 for c in claims["items"] if c["guilt"])
    assert claims["true_retracted"] == 0


def test_hasty_detective_makes_a_supported_but_wrong_accusation(scenario):
    engine = run_investigation(scenario, 4, {"okafor": "hasty"}, [])
    result = evaluate(scenario, engine.state, engine.events)
    assert result["outcome"] == "wrong_accusation" and result["accused"] == "brandt"
    # What she held did meet the standard; it was wrong because exculpatory evidence was never sought.
    assert result["accusation_supported"] is True
    assert result["evidence"]["key_discovered"]["num"] < 6
    assert result["agents"]["okafor"]["prime_correct"] is False
    assert "took(brandt,aurora)" in result["agents"]["okafor"]["false_beliefs"]


def test_baseless_accusation_is_wrong_and_unsupported(scenario):
    engine, result = scripted_run(scenario, {(1, "okafor"): Accuse(suspect="mercer")})
    assert result["outcome"] == "wrong_accusation"
    assert result["accusation_supported"] is False
    assert result["provenance"] == []
    assert result["effort"]["ticks"] == 1


def test_lucky_guess_is_solved_but_unsupported(scenario):
    """Naming the right person without evidence is recorded as correct and unsupported, not as success by merit."""
    engine, result = scripted_run(scenario, {(1, "okafor"): Accuse(suspect="whitlock")})
    assert result["outcome"] == "solved" and result["accusation_supported"] is False
    assert result["evidence"]["key_held_by_lead"]["num"] == 0


def test_idle_investigation_is_unresolved_with_null_ratios(scenario):
    engine, result = scripted_run(scenario, {})
    assert result["outcome"] == "unresolved" and result["close_reason"] == "tick_limit"
    assert result["accused"] is None and result["accusation_supported"] is None
    assert result["claims"]["false_retracted"]["pct"] is None
    assert result["claims"]["unsupported_guilt"]["pct"] is None
    assert result["evidence"]["key_discovered"] == ratio(0, 6)
    assert result["agents"]["okafor"]["belief_accuracy"]["den"] == 0


def test_more_claims_do_not_raise_any_score(scenario):
    """A journalist who publishes an unbacked accusation gains nothing: it is counted against her."""
    quiet, quiet_result = scripted_run(scenario, {})
    script = {
        (1, "nair"): Inspect(source="tip_line", topic="aurora"),
        (2, "nair"): Publish(proposition="took(brandt,aurora)", cited=("E06",)),
        (3, "nair"): Publish(proposition="has_motive(brandt)"),
    }
    loud, loud_result = scripted_run(scenario, script)
    claims = loud_result["claims"]
    assert claims["published_by_agents"] == 2
    assert claims["unsupported"] == ratio(2, 2)
    assert claims["false"]["num"] == 1  # Brandt's motive is real; the accusation is false
    assert loud_result["outcome"] == quiet_result["outcome"] == "unresolved"
    # Hearing the claims changed no listener's score: same decided beliefs, same number correct
    # as in the run where nothing was published.
    for agent in ("okafor", "brandt", "reyes"):
        assert loud_result["agents"][agent]["belief_accuracy"] == quiet_result["agents"][agent]["belief_accuracy"]
        assert loud_result["agents"][agent]["false_beliefs"] == []


def test_belief_accuracy_counts_only_decided_beliefs(scenario, solved):
    result = evaluate(scenario, solved.state, solved.events)
    for agent_id, agent in solved.state.agents.items():
        decided = [
            key for key, b in agent.beliefs.items()
            if b.status in ("believed", "rejected") and scenario.truth_value(Proposition.parse(key)) is not None
        ]
        row = result["agents"][agent_id]["belief_accuracy"]
        assert row["den"] == len(decided)
        assert row["num"] + len(result["agents"][agent_id]["false_beliefs"]) + len(result["agents"][agent_id]["wrongly_rejected"]) == row["den"]


def test_progress_is_spoiler_free(scenario, fresh):
    fresh.run(3)
    data = progress(scenario, fresh.state, fresh.events)
    assert set(data) == {"tick", "max_ticks", "status", "evidence_discovered", "evidence_total", "claims_published", "contradictions_recognized", "requests", "actions"}
    assert data["evidence_total"] == len(scenario.evidence)


def test_interventions_measurably_change_outcomes(scenario):
    """The point of the lab: the same seed under a different condition scores differently."""
    plain = run_investigation(scenario, 3, {}, [])
    leaked = run_investigation(scenario, 3, {}, [(0, "leak_door_log")])
    a = evaluate(scenario, plain.state, plain.events)
    b = evaluate(scenario, leaked.state, leaked.events)
    assert b["claims"]["false"]["num"] > a["claims"]["false"]["num"]
    assert any(c["proposition"] == "took(brandt,aurora)" and c["retracted"] for c in b["claims"]["items"])
    assert a["outcome"] == b["outcome"] == "solved"


def test_a_sweep_reports_the_statistical_median_of_solved_runs():
    """An even sample has no middle element; the median is the mean of the two central ones."""
    from caseforge.__main__ import median, sweep_summary

    assert median([16, 17]) == 16.5
    assert median([17, 15, 16, 22]) == 16.5  # order does not matter
    assert median([15, 16, 17]) == 16 and isinstance(median([15, 16, 17]), int)
    assert median([16, 18]) == 17 and isinstance(median([16, 18]), int)  # a whole mean stays whole
    assert median([]) is None

    def row(outcome, ticks, supported=True):
        category = "unresolved" if supported is None else ("correct" if outcome == "solved" else "wrong") + ("_supported" if supported else "_unsupported")
        return {"outcome": outcome, "category": category, "ticks": ticks, "supported": supported, "false_claims": 0, "false_retracted": 0,
                "withheld_answers": 0, "withholding_noticed": 0, "escalations": 0,
                "false_statements": 0, "false_ever_accepted": 0, "false_accepted_at_close": 0}

    # Only solved runs count: the wrong accusation at tick 3 and the unresolved run at 40 do not move it.
    rows = [row("solved", 16), row("solved", 17), row("wrong_accusation", 3), row("unresolved", 40, None)]
    summary = sweep_summary(rows)
    assert summary["median_ticks_when_solved"] == 16.5
    assert summary["outcomes"] == {"solved": 2, "unresolved": 1, "wrong_accusation": 1}
    assert summary["categories"] == {"correct_supported": 2, "unresolved": 1, "wrong_supported": 1}
    assert sweep_summary([row("unresolved", 40, None)])["median_ticks_when_solved"] is None
