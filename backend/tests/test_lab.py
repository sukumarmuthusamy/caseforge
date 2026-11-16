"""The counterfactual laboratory: manifest, transformations, classification, aggregation.

The expected values here are written out by hand. Nothing in this file decides
what a challenge *should* conclude by asking the reasoner; the recorded results
of the registered collection are checked in test_lab_results.py.
"""

from __future__ import annotations

import copy
import json

import pytest

from caseforge import lab
from caseforge.__main__ import main
from caseforge.engine import verify_run
from caseforge.models import ENGINE_VERSION
from caseforge.reasoning import RULES_VERSION
from caseforge.scenario import lint, load_bundled, load_scenario_data

MANIFEST = lab.load_manifest()


def P(predicate, *args):
    return {"predicate": predicate, "args": list(args)}


def tiny_manifest(ops, base="quiet_substitution"):
    """A manifest with one variant, registered against the running build."""
    manifest = {
        "manifest_version": 1, "label": "test", "frozen": lab.current_baseline([base]),
        "variants": {"v": {"base": base, "revision": 1, "summary": "test", "ops": ops}},
        "challenges": [{
            "id": "c", "kind": "playable", "variant": "v", "category": "test", "culprit": "marsh", "question": "?",
            "expectations": [{"id": "solved", "kind": "ideal", "check": "category_in", "predicted": "holds", "says": "solved", "args": {"among": ["correct_supported"]}}],
        }],
    }
    lab.check_manifest(manifest)
    return manifest


# -- the frozen baseline -------------------------------------------------------


def test_the_collection_is_registered_against_this_build():
    """If this fails, a rule, a policy or a base scenario changed. The recorded results are then
    results of another build: re-register the manifest and re-measure, do not edit the hash."""
    assert lab.baseline_drift(MANIFEST) == []
    assert MANIFEST["frozen"]["rules_version"] == RULES_VERSION == "2026.11-voices"
    assert MANIFEST["frozen"]["engine_version"] == ENGINE_VERSION == "3"


def test_the_collection_says_what_it_is():
    assert "Not an independent benchmark" in MANIFEST["label"]
    assert lab.LABEL == MANIFEST["label"]


def test_a_changed_baseline_is_refused_and_named():
    manifest = copy.deepcopy(MANIFEST)
    manifest["frozen"]["rules_version"] = "2026.11-credibility"
    with pytest.raises(lab.ChallengeError, match="rules_version: registered against '2026.11-credibility', running '2026.11-voices'"):
        lab.run_lab(manifest, ["two_keyholders"])
    results = lab.run_lab(manifest, ["two_keyholders"], allow_drift=True)
    assert results["drift"] == ["rules_version: registered against '2026.11-credibility', running '2026.11-voices'"]
    assert "differs from the one the manifest was registered against" in lab.render_markdown(results)


def test_the_fingerprint_ignores_line_endings_and_notices_a_changed_rule(monkeypatch):
    before = lab.behaviour_fingerprint()
    assert before == lab.behaviour_fingerprint()
    assert len(before) == 16
    monkeypatch.setattr(lab, "BEHAVIOUR_SOURCES", ("reasoning.py",))
    assert lab.behaviour_fingerprint() != before


# -- the manifest ---------------------------------------------------------------


def test_every_category_has_a_challenge():
    categories = {c["category"] for c in MANIFEST["challenges"]}
    assert categories == {"control", "innocent_custodian", "surviving_lie", "mistaken_testimony", "route_variation", "provenance_conflict", "role_permutation"}
    assert categories == set(MANIFEST["categories"])


def test_every_challenge_states_a_culprit_a_prediction_and_an_ideal():
    for challenge in MANIFEST["challenges"]:
        assert challenge["culprit"] and challenge["prediction"] and challenge["question"], challenge["id"]
        kinds = {e["kind"] for e in challenge["expectations"]}
        assert "ideal" in kinds, challenge["id"]
        assert "contract" in kinds, challenge["id"]


def test_playable_and_reasoning_challenges_are_kept_apart():
    playable = [c["id"] for c in lab.select(MANIFEST, ["playable"])]
    reasoning = [c["id"] for c in lab.select(MANIFEST, ["reasoning"])]
    assert len(playable) == 13 and len(reasoning) == 5
    assert not set(playable) & set(reasoning)
    assert all("variant" in lab.find_challenge(MANIFEST, name) for name in playable)
    assert all("variant" not in lab.find_challenge(MANIFEST, name) and "items" in lab.find_challenge(MANIFEST, name) for name in reasoning)
    results = lab.run_lab(MANIFEST, ["two_keyholders"])
    assert list(results["reasoning"]) == ["two_keyholders"] and results["playable"] == {}
    report = lab.render_markdown(results)
    assert "## Reasoning-only fixtures" in report and "## Playable challenges" not in report


def test_selection_by_id_collection_and_category():
    assert [c["id"] for c in lab.select(MANIFEST, ["role_permutation"])] == ["curator_did_it", "curator_did_it_hasty", "curator_did_it_deceptive"]
    assert [c["id"] for c in lab.select(MANIFEST, ["control", "control", "two_keyholders"])] == ["control", "two_keyholders"]
    assert len(lab.select(MANIFEST, [])) == 18
    with pytest.raises(lab.ChallengeError, match="unknown challenge 'nope'"):
        lab.select(MANIFEST, ["nope"])


@pytest.mark.parametrize("broken, message", [
    (lambda m: m["challenges"][0].pop("culprit"), "missing 'culprit'"),
    (lambda m: m["challenges"][0].update(variant="absent"), "unknown variant 'absent'"),
    (lambda m: m["challenges"][0].update(kind="guess"), "kind must be 'playable' or 'reasoning'"),
    (lambda m: m["challenges"][0].update(expectations=[]), "states no expectation"),
    (lambda m: m["challenges"][0]["expectations"][0].update(check="convicted"), "unknown check 'convicted' for a playable challenge"),
    (lambda m: m["challenges"][0]["expectations"][0].update(predicted="probably"), "predicted must be one of"),
    (lambda m: m["challenges"][0]["expectations"][0].update(kind="hope"), "kind must be one of"),
    (lambda m: m["challenges"].append(copy.deepcopy(m["challenges"][0])), "defined twice"),
])
def test_a_malformed_manifest_is_refused_with_the_reason(broken, message):
    manifest = tiny_manifest([])
    broken(manifest)
    with pytest.raises(lab.ChallengeError, match=message):
        lab.check_manifest(manifest)


# -- variants are ordinary scenarios ---------------------------------------------


@pytest.mark.parametrize("variant_id", sorted(MANIFEST["variants"]))
def test_every_variant_is_a_valid_scenario_of_its_own(variant_id):
    scenario = lab.build_variant(MANIFEST, variant_id)
    assert lint(scenario) == []
    base = load_bundled(MANIFEST["variants"][variant_id]["base"])
    assert scenario.id == f"{base.id}.{variant_id}"
    assert scenario.version.startswith(base.version + "+" + variant_id + ".")
    assert scenario.content_hash != base.content_hash
    # The exported file is loadable by the ordinary loader, which lints again.
    assert load_scenario_data(lab.variant_data(MANIFEST, variant_id)).content_hash == scenario.content_hash


def test_building_a_variant_is_deterministic_and_leaves_the_base_alone():
    before = load_bundled("quiet_substitution").content_hash
    first = json.dumps(lab.variant_data(MANIFEST, "curator_did_it"), sort_keys=True)
    second = json.dumps(lab.variant_data(MANIFEST, "curator_did_it"), sort_keys=True)
    assert first == second
    assert lab.base_data("quiet_substitution") == lab.base_data("quiet_substitution")
    assert load_bundled("quiet_substitution").content_hash == before == "3f203e24f527" + before[12:]


def test_the_control_variant_differs_from_the_bundled_case_only_in_its_name():
    data = lab.variant_data(MANIFEST, "control")
    base = lab.base_data("quiet_substitution")
    assert data["private"] == base["private"]
    changed = {key for key in base["public"] if data["public"][key] != base["public"][key]}
    assert changed == {"id", "version"}


def test_the_permuted_culprit_is_carried_by_the_evidence_not_only_by_the_truth_block():
    """Culprit: Fenwick. The instruments that date the exchange were rewritten with him."""
    scenario = lab.build_variant(MANIFEST, "curator_did_it")
    base = load_bundled("quiet_substitution")
    said = lambda s, e: [p.key for p in s.evidence[e].asserts]  # noqa: E731
    assert said(base, "E12") == said(base, "E14") == ["crime_at(treasury,thu_evening)"]
    assert said(scenario, "E12") == said(scenario, "E14") == ["crime_at(treasury,fri_evening)"]
    assert scenario.evidence["E12"].text != base.evidence["E12"].text
    assert sorted(set(scenario.evidence) ^ set(base.evidence)) == []


# -- invalid transformations ------------------------------------------------------


def test_changing_only_the_culprit_field_is_rejected_by_the_lint():
    """The shortcut the laboratory must not allow: a new name in the truth block, the old evidence."""
    manifest = tiny_manifest([{"op": "truth.set", "why": "shortcut", "fields": {"culprit": "fenwick"}}])
    with pytest.raises(lab.ChallengeError) as caught:
        lab.build_variant(manifest, "v")
    assert "rejected by the scenario lint" in str(caught.value)
    assert "truth.facts must state that the culprit took the object" in str(caught.value)
    assert "the records hale can acquire point at 'marsh'" in str(caught.value)


def test_a_culprit_swap_without_rewriting_the_instruments_is_rejected():
    """Truth says Fenwick on Friday, the logger and the laboratory still say Thursday: records must be true."""
    ops = [
        {"op": "truth.facts", "why": "who and when", "remove": [P("took", "marsh", "ashby_hours"), P("crime_at", "treasury", "thu_evening")],
         "add": [P("took", "fenwick", "ashby_hours"), P("crime_at", "treasury", "fri_evening")]},
        {"op": "truth.set", "why": "culprit", "fields": {"culprit": "fenwick", "key_facts": [P("took", "fenwick", "ashby_hours")]}},
    ]
    with pytest.raises(lab.ChallengeError) as caught:
        lab.build_variant(tiny_manifest(ops), "v")
    message = str(caught.value)
    assert "rejected by the scenario lint" in message
    assert "E12" in message and "E14" in message


def test_a_false_record_is_rejected():
    ops = [{"op": "evidence.set", "id": "E20", "why": "a camera that lies", "fields": {"asserts": [P("at", "castellan", "treasury", "thu_evening")]}}]
    with pytest.raises(lab.ChallengeError, match="E20"):
        lab.build_variant(tiny_manifest(ops), "v")


def test_removing_what_the_case_rests_on_is_rejected_as_unsolvable():
    ops = [{"op": "evidence.remove", "id": "E13", "why": "no lock examination"},
           {"op": "truth.set", "why": "follow", "fields": {"key_evidence": ["E07", "E12", "E14", "E15", "E17"]}}]
    with pytest.raises(lab.ChallengeError, match="rejected by the scenario lint"):
        lab.build_variant(tiny_manifest(ops), "v")


@pytest.mark.parametrize("op, message", [
    ({"op": "evidence.delete", "id": "E01", "why": "x"}, r"edit 1 \(evidence.delete\): unknown edit"),
    ({"op": "evidence.remove", "id": "E99", "why": "x"}, r"edit 1 \(evidence.remove\): no evidence 'E99'"),
    ({"op": "evidence.remove", "id": "E01"}, "every edit says why"),
    ({"op": "evidence.set", "id": "E01", "why": "x", "fields": {"weight": 9}}, "unknown field 'weight'"),
    ({"op": "evidence.set", "id": "E01", "why": "x", "fields": {"kind": "record"}}, "changes nothing"),
    ({"op": "evidence.set", "id": "E01", "why": "x", "fields": {"id": "E77"}}, "an id cannot be changed"),
    ({"op": "evidence.set", "id": "E01", "why": "x"}, "missing 'fields'"),
    ({"op": "evidence.set", "id": "E01", "why": "x", "fields": {"kind": "forensic"}, "force": True}, "unknown keys"),
    ({"op": "evidence.add", "why": "x", "record": {"id": "E01"}}, "evidence 'E01' already exists"),
    ({"op": "source.set", "id": "attic", "why": "x", "fields": {"searchable": []}}, "no source 'attic'"),
    ({"op": "truth.set", "why": "x", "fields": {"facts": []}}, "unknown field 'facts'"),
    ({"op": "truth.facts", "why": "x"}, "nothing to add or remove"),
    ({"op": "truth.facts", "why": "x", "remove": [P("took", "ibarra", "ashby_hours")]}, "is not a fact"),
    ({"op": "truth.facts", "why": "x", "add": [P("crime_used", "case_key")]}, "is already a fact"),
    ({"op": "observation.remove", "why": "x", "agent": "hale", "proposition": P("at", "hale", "great_hall", "thu_evening")}, "hale has no observation"),
    ({"op": "agenda.set", "why": "x", "agent": "osei", "agenda": None}, "osei has no agenda to remove"),
    ({"op": "intervention.remove", "why": "x", "id": "nope"}, "no intervention 'nope'"),
])
def test_an_edit_that_cannot_be_applied_is_refused_with_its_position_and_reason(op, message):
    with pytest.raises(lab.ChallengeError, match=message):
        lab.apply_ops(lab.base_data("quiet_substitution"), [op])


def test_a_malformed_record_is_refused_by_the_models():
    ops = [{"op": "evidence.add", "why": "x", "record": {"id": "E30", "kind": "prophecy"}}]
    with pytest.raises(lab.ChallengeError, match="not a well-formed scenario"):
        lab.build_variant(tiny_manifest(ops), "v")


def test_an_unknown_agent_or_intervention_in_a_challenge_is_refused():
    manifest = tiny_manifest([])
    manifest["challenges"][0]["policies"] = {"poirot": "hasty"}
    with pytest.raises(lab.ChallengeError, match="'poirot' is not an agent"):
        lab.run_lab(manifest, ["c"], seeds=[0])
    manifest["challenges"][0]["policies"] = {}
    manifest["challenges"][0]["interventions"] = [["confession", 3]]
    with pytest.raises(lab.ChallengeError, match="no intervention 'confession'"):
        lab.run_lab(manifest, ["c"], seeds=[0])


# -- classification and aggregation, on rows written by hand ------------------------

CHALLENGE = {
    "id": "x", "expectations": [
        {"id": "law", "kind": "contract", "check": "replay_verifies", "predicted": "holds", "says": "law"},
        {"id": "setup", "kind": "design", "check": "culprit_is", "predicted": "holds", "says": "setup"},
        {"id": "good", "kind": "ideal", "check": "category_in", "predicted": "holds", "says": "good"},
    ],
}


@pytest.mark.parametrize("law, setup, good, expected", [
    (True, True, True, "meets_ideal"),
    (True, True, False, "falls_short"),
    (True, False, True, "invalid_instance"),
    (True, False, False, "invalid_instance"),  # a run that does not test the thing says nothing about the reasoning
    (False, True, True, "contract_violation"),
    (False, False, False, "contract_violation"),  # a defect is named first
    (None, True, True, "meets_ideal"),  # not checked is not failed
    (None, None, False, "falls_short"),
])
def test_a_verdict_separates_defects_from_invalid_instances_from_limits(law, setup, good, expected):
    assert lab.verdict(CHALLENGE, {"law": law, "setup": setup, "good": good}) == expected


def row(seed, category, ticks, good, law=True, replay=True, **extra):
    """A run row with the fields the aggregation reads. Outcome follows from the category."""
    outcome = {"correct_supported": "solved", "correct_unsupported": "solved", "wrong_supported": "wrong_accusation",
               "wrong_unsupported": "wrong_accusation", "unresolved": "unresolved"}[category]
    held = {"law": law, "setup": True, "good": good}
    base = {
        "seed": seed, "category": category, "outcome": outcome, "accused": {"solved": "marsh", "wrong_accusation": "fenwick", "unresolved": None}[outcome],
        "ticks": ticks, "actions": 10 * ticks, "key_evidence": [5, 6], "key_evidence_held_by_accuser": [4, 6], "all_evidence": [20, 21],
        "contradictions_recognized": [1, 2], "contradictions_resolved_correctly": [3, 8], "statements": 7, "false_statements": 5,
        "false_ever_accepted": 3, "false_accepted_at_close": 0, "false_unrefuted_at_close": 1, "credibility_revisions": 2,
        "impeached_by_accuser": ["ibarra"] if seed % 2 else [], "withheld_answers": 1, "withholding_noticed": 1, "escalations": seed % 2,
        "replay": None if replay is None else {"chain": True, "fold": True, "decisions": replay, "policies": True},
        "expectations": held, "verdict": lab.verdict(CHALLENGE, held),
    }
    base.update(extra)
    return base


def test_aggregation_counts_each_category_and_uses_the_statistical_median():
    rows = [
        row(0, "correct_supported", 17, True),
        row(1, "correct_supported", 20, True),
        row(2, "correct_unsupported", 12, False),
        row(3, "correct_supported", 30, True, replay=False),
        row(4, "wrong_supported", 9, False),
        row(5, "wrong_unsupported", 8, False),
        row(6, "unresolved", 40, False, replay=None),
        row(7, "unresolved", 40, False, law=False),
    ]
    a = lab.aggregate_playable(CHALLENGE, rows)
    assert a["runs"] == 8
    assert a["categories"] == {"correct_supported": 3, "correct_unsupported": 1, "wrong_supported": 1, "wrong_unsupported": 1, "unresolved": 2}
    assert sum(a["categories"].values()) == a["runs"]
    assert a["verdicts"] == {"meets_ideal": 3, "falls_short": 4, "invalid_instance": 0, "contract_violation": 1}
    assert a["false_accusations"] == 2
    assert a["accused"] == {"None": 2, "fenwick": 2, "marsh": 4}
    # Solved runs took 12, 17, 20 and 30 ticks: the median of four values is the mean of the middle two.
    assert a["median_ticks_when_solved"] == 18.5
    assert a["ticks_range_when_solved"] == [12, 30]
    # All eight: 8, 9, 12, 17, 20, 30, 40, 40 -> (17 + 20) / 2
    assert a["median_ticks"] == 18.5
    assert a["key_evidence_discovered"] == [40, 48]
    assert a["key_evidence_held_by_accuser"] == [32, 48]
    assert a["contradictions_recognized"] == [8, 16]
    assert (a["statements"], a["false_statements"], a["false_ever_accepted"], a["false_accepted_at_close"], a["false_unrefuted_at_close"]) == (56, 40, 24, 0, 8)
    assert a["credibility_revisions"] == 16
    assert a["runs_where_accuser_impeached_someone"] == 4
    assert a["runs_with_escalation"] == 4
    assert a["replay"] == {"verified": 7, "passed": 6, "not_run": 1}
    by_id = {e["id"]: e for e in a["expectations"]}
    assert (by_id["good"]["held"], by_id["good"]["of"], by_id["good"]["observed"], by_id["good"]["prediction_right"]) == (3, 8, "mixed", False)
    assert by_id["good"]["failed_seeds"] == [2, 4, 5, 6, 7]
    assert (by_id["law"]["held"], by_id["law"]["of"], by_id["law"]["observed"]) == (7, 8, "mixed")
    assert (by_id["setup"]["held"], by_id["setup"]["observed"], by_id["setup"]["prediction_right"]) == (8, "holds", True)


def test_an_expectation_that_never_applied_is_not_counted_as_held():
    rows = [row(0, "correct_supported", 17, None), row(1, "correct_supported", 19, None)]
    good = lab.aggregate_playable(CHALLENGE, rows)["expectations"][2]
    assert (good["held"], good["of"], good["observed"], good["prediction_right"]) == (0, 0, "not_applicable", None)


def test_the_median_of_an_odd_and_an_empty_list():
    assert lab.median([3, 1, 2]) == 2
    assert lab.median([1, 2]) == 1.5
    assert lab.median([]) is None
    assert lab.aggregate_playable(CHALLENGE, [row(0, "unresolved", 40, False)])["median_ticks_when_solved"] is None


def test_failed_cases_name_the_run_and_how_to_run_it_again():
    rows = [row(0, "correct_supported", 17, True), row(3, "wrong_supported", 9, False), row(5, "unresolved", 40, False, law=False)]
    results = {
        "config": {"policy_overrides": {}},
        "playable": {"x": {"aggregate": lab.aggregate_playable(CHALLENGE, rows), "runs": rows}},
        "reasoning": {},
    }
    cases = lab.failed_cases(results)
    assert [(c["seed"], c["verdict"], c["failed"]) for c in cases] == [
        (3, "falls_short", ["good (ideal)"]),
        (5, "contract_violation", ["law (contract)", "good (ideal)"]),
    ]
    assert cases[0]["reproduce"] == "python -m caseforge lab reproduce x --seed 3"
    results["config"]["policy_overrides"] = {"hale": "hasty"}
    assert lab.failed_cases(results)[0]["reproduce"] == "python -m caseforge lab reproduce x --seed 3 --policy hale=hasty"


def test_seed_ranges():
    assert lab.parse_seeds("0-3") == [0, 1, 2, 3]
    assert lab.parse_seeds("7") == [7]


# -- running: the control, which is the bundled case ----------------------------------


def test_the_control_runs_through_the_ordinary_engine_and_replays():
    """Culprit: Marsh. Seed 7 of the bundled case is solved at tick 19 (README)."""
    challenge = lab.find_challenge(MANIFEST, "control")
    result_row, run = lab.run_playable(MANIFEST, challenge, 7, replay=True)
    assert (result_row["category"], result_row["accused"], result_row["supported"]) == ("correct_supported", "marsh", True)
    assert result_row["replay"] == {"chain": True, "fold": True, "decisions": True, "policies": True}
    assert result_row["verdict"] == "meets_ideal"
    assert result_row["rejected_actions"] == 0
    # The log is an ordinary one: it verifies against the variant with nothing from the laboratory.
    checks = verify_run(run.scenario, run.events)
    assert all(checks[level]["ok"] for level in lab.REPLAY_LEVELS)
    assert checks["head_hash"] == result_row["head"]
    # And it is the same investigation as the bundled case under another scenario id.
    again, _ = lab.run_playable(MANIFEST, challenge, 7)
    assert again["head"] == result_row["head"] and again["replay"] is None
    assert (again["ticks"], again["actions"]) == (result_row["ticks"], result_row["actions"])


def test_a_policy_override_is_recorded_as_not_the_registered_experiment():
    results = lab.run_lab(MANIFEST, ["control"], seeds=[0], replay="none", overrides={"hale": "hasty"})
    assert results["config"]["registered_configuration"] is False
    assert results["playable"]["control"]["definition"]["policies"] == {"hale": "hasty"}
    assert "Not the registered configuration" in lab.render_markdown(results)
    assert "--policy hale=hasty" in "".join(c["reproduce"] for c in lab.failed_cases(results)) or not lab.failed_cases(results)


def test_a_challenge_that_asks_for_an_impossible_check_is_refused():
    manifest = tiny_manifest([])
    manifest["challenges"][0]["expectations"][0]["args"] = {"amongst": ["x"]}
    with pytest.raises(lab.ChallengeError, match="cannot be evaluated"):
        lab.run_lab(manifest, ["c"], seeds=[0], replay="none")


# -- the command line -------------------------------------------------------------------


def test_cli_list_show_check_and_export(capsys, tmp_path):
    assert main(["lab", "list"]) == 0
    out = capsys.readouterr().out
    assert "Not an independent benchmark" in out and "curator_did_it_hasty" in out and "this build" in out
    assert main(["lab", "show", "curator_did_it"]) == 0
    out = capsys.readouterr().out
    assert "culprit: fenwick" in out and "evidence.set E12" in out and "predicted beforehand" in out
    assert main(["lab", "check"]) == 0
    out = capsys.readouterr().out
    assert out.count(": ok") == len(MANIFEST["variants"]) and "sealed_motive" in out and "hale: escalation" in out
    target = tmp_path / "custodian.json"
    assert main(["lab", "export", "custodian", "--out", str(target)]) == 0
    capsys.readouterr()
    # The exported counterfactual is playable with the ordinary commands.
    assert main(["validate", str(target)]) == 0
    assert "quiet_substitution.custodian" not in capsys.readouterr().err
    assert main(["lab", "show", "nope"]) == 2
    assert "unknown challenge 'nope'" in capsys.readouterr().err


def test_cli_run_writes_json_and_markdown_and_reproduce_repeats_a_run(capsys, tmp_path):
    out_dir = tmp_path / "out"
    assert main(["lab", "run", "control", "two_keyholders", "--seeds", "7", "--replay", "every", "--out", str(out_dir)]) == 0
    text = capsys.readouterr().out
    assert "control" in text and "two_keyholders" in text
    results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert results["config"]["seeds"] == [7] and results["drift"] == []
    recorded = results["playable"]["control"]["runs"][0]
    report = (out_dir / "report.md").read_text(encoding="utf-8")
    assert "## Playable challenges" in report and "## Reasoning-only fixtures" in report
    assert main(["lab", "reproduce", "control", "--seed", "7", "--json"]) == 0
    again = json.loads(capsys.readouterr().out)["row"]
    assert again == recorded
    assert main(["lab", "reproduce", "two_keyholders"]) == 0
    assert "verdict:" in capsys.readouterr().out


# -- the manifest schema version ---------------------------------------------------


@pytest.mark.parametrize("version", [999, 0, 2, -1, "1", 1.0, None, True, [1]])
def test_an_unsupported_manifest_version_is_refused_before_anything_runs(version):
    """Version 999 used to be accepted, reported as registered, and run with this schema's meaning."""
    manifest = copy.deepcopy(MANIFEST)
    manifest["manifest_version"] = version
    with pytest.raises(lab.ChallengeError, match="manifest_version|version"):
        lab.check_manifest(manifest)
    with pytest.raises(lab.ChallengeError):
        lab.run_lab(manifest, ["two_keyholders"])  # data handed over directly is checked too
    with pytest.raises(lab.ChallengeError):
        lab.run_lab(manifest, ["two_keyholders"], allow_drift=True)  # the drift override does not excuse it


def test_the_refusal_names_the_version_and_what_to_do():
    manifest = copy.deepcopy(MANIFEST)
    manifest["manifest_version"] = 999
    with pytest.raises(lab.ChallengeError) as caught:
        lab.check_manifest(manifest)
    message = str(caught.value)
    assert "version 999 is not supported" in message and "reads version 1" in message and "converted" in message
    manifest["manifest_version"] = "1"
    with pytest.raises(lab.ChallengeError, match="must be an integer, got '1'"):
        lab.check_manifest(manifest)
    del manifest["manifest_version"]
    with pytest.raises(lab.ChallengeError, match="missing 'manifest_version'"):
        lab.check_manifest(manifest)
    with pytest.raises(lab.ChallengeError, match="expected a JSON object"):
        lab.check_manifest([])


def test_version_1_still_loads_and_runs_as_before():
    assert MANIFEST["manifest_version"] == 1 and lab.SUPPORTED_MANIFEST_VERSIONS == (1,)
    results = lab.run_lab(MANIFEST, ["two_keyholders"])
    assert results["manifest_version"] == 1 and results["drift"] == []
    assert results["config"]["registered_configuration"] is True


def test_cli_refuses_an_unsupported_manifest_and_writes_nothing(capsys, tmp_path):
    bad = copy.deepcopy(MANIFEST)
    bad["manifest_version"] = 999
    path = tmp_path / "m999.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    out = tmp_path / "out"
    for argv in (
        ["lab", "run", "two_keyholders", "--manifest", str(path), "--seeds", "0", "--json"],
        ["lab", "run", "two_keyholders", "--manifest", str(path), "--seeds", "0", "--allow-drift", "--out", str(out)],
        ["lab", "list", "--manifest", str(path)],
        ["lab", "check", "--manifest", str(path)],
        ["lab", "reproduce", "two_keyholders", "--manifest", str(path)],
    ):
        assert main(argv) == 2, argv
        captured = capsys.readouterr()
        assert "version 999 is not supported" in captured.err
        assert captured.out == ""  # nothing that could be mistaken for a result
    assert not out.exists()
