"""The recorded results of collection 1, and whether this build still produces them.

RECORDED was copied from the registered run of 2026-11-15, which followed the
registration of the expectations in the unpublished development history. A
full re-run on 2026-11-16, after a wording-only revision of the manifest,
reproduced every figure (docs/LAB.md). These are
observations, not targets: several are failures of an ideal and must stay
visible as such. If a rule or policy change moves any of them, the baseline
test in test_lab.py fails first; re-register and re-measure, and say what
moved. Do not edit a number here to make a test pass.

The reasoning fixtures are also worked out by hand below, with the culprit
stated, so that what the reasoner does is checked against arithmetic and not
against itself.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caseforge import lab

MANIFEST = lab.load_manifest()
RESULTS_FILE = Path(__file__).resolve().parents[2] / "docs" / "lab" / "collection-1" / "results.json"
STORED = json.loads(RESULTS_FILE.read_text(encoding="utf-8"))

# challenge: (correct+supported, correct unsupported, wrong+supported, wrong unsupported, unresolved, median ticks when solved)
RECORDED = {
    "control": (40, 0, 0, 0, 0, 19),
    "custodian": (40, 0, 0, 0, 0, 18),
    "custodian_hasty": (16, 0, 24, 0, 0, 19),
    "mistaken_witness": (40, 0, 0, 0, 0, 24),
    "lie_survives": (0, 0, 0, 0, 40, None),
    "second_routes": (40, 0, 0, 0, 0, 24),
    "sealed_motive": (0, 0, 0, 0, 40, None),
    "sealed_motive_deceptive": (26, 0, 0, 0, 14, 20),
    "more_witnesses": (40, 0, 0, 0, 0, 21),
    "more_witnesses_hasty": (0, 0, 40, 0, 0, None),
    "curator_did_it": (40, 0, 0, 0, 0, 17),
    "curator_did_it_hasty": (40, 0, 0, 0, 0, 13),
    "curator_did_it_deceptive": (40, 0, 0, 0, 0, 18),
}

# The predictions the author got wrong, as (challenge, expectation): (predicted, observed).
WRONG_PREDICTIONS = {
    ("custodian_hasty", "registrar_not_accused"): ("mixed", "holds"),
    ("lie_survives", "lie_not_accepted"): ("mixed", "fails"),
    ("more_witnesses_hasty", "curator_not_accused"): ("mixed", "fails"),
    ("more_witnesses_hasty", "solved_with_support"): ("mixed", "fails"),
}


def test_the_stored_results_are_the_registered_experiment():
    assert STORED["label"] == lab.LABEL
    assert STORED["drift"] == []
    assert STORED["registered_against"] == MANIFEST["frozen"] == STORED["running"]
    assert STORED["config"] == {"seeds": list(range(40)), "replay": "every", "policy_overrides": {}, "registered_configuration": True}
    assert list(STORED["playable"]) == [c["id"] for c in lab.select(MANIFEST, ["playable"])]
    assert list(STORED["reasoning"]) == [c["id"] for c in lab.select(MANIFEST, ["reasoning"])]


@pytest.mark.parametrize("challenge_id", sorted(RECORDED))
def test_the_stored_results_say_what_is_recorded_here(challenge_id):
    aggregate = STORED["playable"][challenge_id]["aggregate"]
    categories = aggregate["categories"]
    assert (
        categories["correct_supported"], categories["correct_unsupported"], categories["wrong_supported"],
        categories["wrong_unsupported"], categories["unresolved"], aggregate["median_ticks_when_solved"],
    ) == RECORDED[challenge_id]
    assert sum(categories.values()) == aggregate["runs"] == 40
    # Every one of the 520 runs was replayed, and every replay agreed.
    assert aggregate["replay"] == {"verified": 40, "passed": 40, "not_run": 0}
    assert aggregate["verdicts"]["contract_violation"] == 0
    assert aggregate["verdicts"]["invalid_instance"] == 0


@pytest.mark.parametrize("challenge_id", sorted(RECORDED))
def test_each_stored_aggregate_follows_from_its_stored_runs(challenge_id):
    """Aggregation is independent of running: recompute it from the rows on disk."""
    entry = STORED["playable"][challenge_id]
    assert lab.aggregate_playable(lab.find_challenge(MANIFEST, challenge_id), entry["runs"]) == entry["aggregate"]


def test_the_wrong_predictions_are_exactly_the_recorded_ones():
    wrong = {}
    for challenge_id, entry in STORED["playable"].items():
        for e in entry["aggregate"]["expectations"]:
            if e["prediction_right"] is False:
                wrong[(challenge_id, e["id"])] = (e["predicted"], e["observed"])
    for challenge_id, entry in STORED["reasoning"].items():
        for e in entry["expectations"]:
            if e["prediction_right"] is False:
                wrong[(challenge_id, e["id"])] = (e["predicted"], e["observed"])
    assert wrong == WRONG_PREDICTIONS


# One success, and the failures that must stay visible. (challenge, seed): (category, accused, ticks, first 12 of the head hash)
PINNED_RUNS = {
    ("control", 7): ("correct_supported", "marsh", 20, "238fc656b44d"),
    ("curator_did_it_hasty", 3): ("correct_supported", "fenwick", 9, "288808eb23fd"),
    ("sealed_motive_deceptive", 3): ("correct_supported", "marsh", 20, "80e6da6e96d4"),
    ("sealed_motive_deceptive", 0): ("unresolved", None, 40, "92e1047be0cd"),
    ("lie_survives", 0): ("unresolved", None, 40, "a9ce531fe6cb"),
    ("custodian_hasty", 3): ("wrong_supported", "fenwick", 9, "d3a7efb13df2"),
    ("more_witnesses_hasty", 7): ("wrong_supported", "fenwick", 12, "e0ef40d01ae1"),
}


@pytest.mark.parametrize("challenge_id, seed", sorted(PINNED_RUNS))
def test_a_recorded_run_is_reproduced_exactly(challenge_id, seed):
    """The same challenge and seed give the same row, down to the head hash, and the log replays."""
    row, _run = lab.run_playable(MANIFEST, lab.find_challenge(MANIFEST, challenge_id), seed, replay=True)
    assert (row["category"], row["accused"], row["ticks"], row["head"][:12]) == PINNED_RUNS[(challenge_id, seed)]
    assert row == STORED["playable"][challenge_id]["runs"][seed]
    assert row["replay"] == {"chain": True, "fold": True, "decisions": True, "policies": True}


def test_known_failure_an_unrefutable_lie_leaves_the_case_open():
    """Culprit: Marsh. The registrar's false alibi for her is told three times and passed on twice.

    Nothing the team can hold contradicts it, so no listener ever rejects it and the conservator's
    opportunity stays contested. This is a limit of the rules, recorded, not a defect.
    """
    row, run = lab.run_playable(MANIFEST, lab.find_challenge(MANIFEST, "lie_survives"), 0)
    assert row["verdict"] == "falls_short"
    assert (row["category"], row["accused"]) == ("unresolved", None)
    assert (row["false_statements"], row["false_ever_accepted"], row["false_accepted_at_close"], row["false_unrefuted_at_close"]) == (5, 5, 2, 5)
    assert row["expectations"]["one_voice_one_vote"] is True  # the contract holds while the ideal fails
    # The inspector catches out the honest, mistaken steward and the two who said Friday; never the liar.
    assert row["impeached_by_accuser"] == ["alder", "marsh", "pruitt"]
    assert (row["withheld_answers"] > 0, row["withholding_noticed"], row["escalations"]) == (True, 0, 0)
    assert run.state.agents["hale"].credibility.get("ibarra") is None or run.state.agents["hale"].credibility["ibarra"].current.standing != "impeached"


def test_known_failure_haste_convicts_the_curator_when_recollection_outweighs_one_instrument():
    """Culprit: Marsh. Accused: Fenwick, with the standard met on what the inspector held."""
    row, _run = lab.run_playable(MANIFEST, lab.find_challenge(MANIFEST, "more_witnesses_hasty"), 7)
    assert (row["category"], row["accused"], row["supported"], row["verdict"]) == ("wrong_supported", "fenwick", True, "falls_short")


# -- reasoning-only fixtures, by hand ------------------------------------------------
# Weights: forensic 5, record 4, testimony 2 (1 for a suspect speaking of himself). A leg is
# believed at net 2. Opportunity strong 3, weak 1, contested 0; means 2; strong motive 2.
# The standard needs all three legs and a lead of 3.


def reasoning(challenge_id):
    return lab.run_reasoning(lab.find_challenge(MANIFEST, challenge_id))


def test_two_records_disagree_and_nobody_is_convicted():
    """Culprit: Bob. Door log 4 for the vault, camera 4 for the cafe: net 0."""
    r = reasoning("two_records_disagree")
    assert r["beliefs"]["at(bob,vault,night)"] == {"support": 4, "contra": 4, "status": "disputed"}
    assert r["suspects"]["bob"] == {"score": 4, "opportunity": "contested", "means": True, "motive": "strong"}  # 0 + 2 + 2
    assert (r["convicted"], r["category"], r["verdict"]) == (None, "unresolved", "meets_ideal")


def test_known_failure_four_recollections_overturn_a_forensic_finding_and_convict_an_innocent():
    """Culprit: Bob, at night. Convicted: Ann.

    Evening: four witnesses, 2 each = 8. Night: one forensic finding = 5. Net for the evening 3,
    so it is believed and the night rejected. Ann, in the vault that evening with the key and a
    motive: 3 + 2 + 2 = 7. Bob has no presence in the believed slot and no key then: motive only, 2.
    """
    r = reasoning("instrument_outvoted")
    assert r["beliefs"]["crime_at(vault,evening)"] == {"support": 8, "contra": 5, "status": "believed"}
    assert r["beliefs"]["crime_at(vault,night)"] == {"support": 5, "contra": 8, "status": "rejected"}
    assert r["suspects"]["ann"]["score"] == 7 and r["suspects"]["bob"]["score"] == 2
    assert (r["convicted"], r["category"], r["verdict"]) == ("ann", "wrong_supported", "falls_short")
    assert r["expectations"] == {"order": True, "ann_not_convicted": False, "finding_stands": False}


def test_one_voice_naming_two_doors_counts_once():
    """Culprit: Bob. w1 says vault and vault door (one zone): 2, not 4. w2 says cafe: 2. Net 0."""
    r = reasoning("one_voice_two_doors")
    assert r["beliefs"]["at(ann,vault,night)"] == {"support": 2, "contra": 2, "status": "disputed"}
    assert r["suspects"]["ann"]["opportunity"] == "contested"
    assert (r["convicted"], r["verdict"]) == (None, "meets_ideal")


def test_known_failure_an_admission_is_discounted_like_a_denial():
    """Culprit: Bob. His own word that he was there weighs 1: tentative, opportunity weak. 1 + 2 + 2 = 5."""
    r = reasoning("admission_against_interest")
    assert r["beliefs"]["at(bob,vault,night)"] == {"support": 1, "contra": 0, "status": "tentative"}
    assert r["suspects"]["bob"] == {"score": 5, "opportunity": "weak", "means": True, "motive": "strong"}
    assert (r["convicted"], r["category"], r["verdict"]) == (None, "unresolved", "falls_short")


def test_two_keyholders_and_the_one_who_was_there():
    """Culprit: Bob. Bob 3 + 2 + 2 = 7. Ann, key and motive, no presence known: 0 + 2 + 2 = 4. Lead 3."""
    r = reasoning("two_keyholders")
    assert r["suspects"]["bob"]["score"] == 7 and r["suspects"]["ann"]["score"] == 4
    assert (r["convicted"], r["category"], r["verdict"]) == ("bob", "correct_supported", "meets_ideal")


def test_the_stored_reasoning_results_are_the_actual_ones():
    for challenge_id, entry in STORED["reasoning"].items():
        assert entry["result"] == reasoning(challenge_id), challenge_id
    verdicts = {name: entry["result"]["verdict"] for name, entry in STORED["reasoning"].items()}
    assert verdicts == {
        "two_records_disagree": "meets_ideal", "instrument_outvoted": "falls_short", "one_voice_two_doors": "meets_ideal",
        "admission_against_interest": "falls_short", "two_keyholders": "meets_ideal",
    }


def test_the_committed_report_is_what_the_stored_results_render_to():
    report = (RESULTS_FILE.parent / "report.md").read_text(encoding="utf-8")
    assert report == lab.render_markdown(STORED)
