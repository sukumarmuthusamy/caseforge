"""Internal challenge fixtures for the reasoner, run against a frozen rule set.

What this is, and is not
------------------------
These cases were written by the same author as the reasoner. They are
additional internal fixtures. They are not an independently authored external
benchmark, and passing them says nothing about cases nobody here thought of.

How they were made
------------------
1. The rules were frozen first: `reasoning.RULES_VERSION` "2026.11-credibility".
2. Each case below was then written down with what a careful human
   investigator should conclude from the same information (`ideal`), before
   the reasoner was run on it.
3. The reasoner was run once and the result recorded. Where it fell short of
   the ideal, the case is listed under LIMITS with what the reasoner does
   instead, and the rules were left alone. Nothing was tuned to pass.

A caveat that follows from the first paragraph: the author knew the rules, and
wrote down beforehand which cases would fall short. The single run agreed with
every one of those predictions. So this file documents weaknesses its author
could already see. It has not been shown to find ones he could not.

Three kinds of test, kept apart on purpose:

- **contracts**: properties that must hold for any input. A failure is a bug.
- **behaviour**: cases where the frozen rules reach the ideal conclusion.
- **limits**: cases where they do not. Each is an expected failure of the
  ideal (`xfail(strict=True)`), followed by a test stating literally what
  happens instead. If a later rule change makes one pass, the suite fails
  until the case is moved, so the list cannot silently go stale.

Recorded result for RULES_VERSION 2026.11-credibility: see RESULTS at the
bottom, checked by `test_the_recorded_results_are_the_actual_results`.

Rule set history
----------------
- 2026.11-credibility: the set these cases were written against.
- 2026.11-voices: one correction made after a review. A voice that names two
  spots in one zone counts once for that zone, as it already did for one
  spot. No case here has that pattern, the correction was not made with these
  cases in view, and the recorded results are unchanged: the same seven reach
  the ideal and the same six do not. The limit messages below still name the
  rule set they were first recorded against.

The world is the one from test_reasoning_cases.py: suspects Ann, Bob and Cy;
the gem was in the vault; w1 and w2 are witnesses who are not suspects. In
every case the real culprit is stated, and is never given to the reasoner.
"""

from __future__ import annotations

import itertools

import pytest

from caseforge.reasoning import RULES_VERSION, meets_standard, revise

from .test_reasoning_cases import (
    ANN_CAFE,
    ANN_MOTIVE,
    BOB_HAD_TOOL,
    BOB_MOTIVE,
    BOB_VAULT,
    SUSPECTS,
    TOOL,
    WHEN_S1,
    ctx,
    item,
    said,
)

FROZEN_RULES = "2026.11-voices"

ANN_AT_VAULT = item("roster", "record", "at(ann,vault,s1)")  # she works there: lawful
ANN_HAD_TOOL = item("issue", "record", "had(ann,crowbar,s1)")  # issued to her: lawful


def convicted(revision) -> str | None:
    """Whom the standard of proof is met for, if anyone."""
    met = [s for s in SUSPECTS if meets_standard(revision.suspects, s)]
    assert len(met) <= 1
    return met[0] if met else None


def status(revision, key: str) -> str:
    return revision.beliefs[key].status if key in revision.beliefs else "unknown"


def standing(revision, voice: str) -> str | None:
    return revision.credibility[voice].standing if voice in revision.credibility else None


# Each case: the items, the real culprit, and the ideal as a list of (description, check).
CASES = {
    # 1. An innocent person with lawful access to the key or tool.
    "lawful access without motive": {
        "culprit": "bob",
        "items": [WHEN_S1, TOOL, ANN_AT_VAULT, ANN_HAD_TOOL],
        "ideal": [
            ("nobody is convicted on access alone", lambda r: convicted(r) is None),
            ("her guilt is not believed", lambda r: status(r, "took(ann,gem)") != "believed"),
        ],
    },
    "lawful access and an ordinary motive": {
        # Ann works in the vault, was issued the tool and has debts like anyone. Bob left no trace.
        "culprit": "bob",
        "items": [WHEN_S1, TOOL, ANN_AT_VAULT, ANN_HAD_TOOL, ANN_MOTIVE],
        "ideal": [
            ("an innocent person is not convicted because the culprit left no records", lambda r: convicted(r) is None),
        ],
    },
    # 2. True but misleading testimony.
    "one true sighting completes a case against an innocent": {
        # w1 truthfully saw Ann at the vault. Nothing else places her there.
        "culprit": "bob",
        "items": [WHEN_S1, TOOL, ANN_HAD_TOOL, ANN_MOTIVE, said("sight", "w1", "at(ann,vault,s1)")],
        "ideal": [
            ("a single unchecked witness is not enough for the opportunity leg", lambda r: convicted(r) is None),
        ],
    },
    # 3. False accusations supported by incomplete evidence.
    "many accusers and a motive": {
        "culprit": "ann",
        "items": [
            WHEN_S1, BOB_MOTIVE,
            item("c1", "hearsay", "took(bob,gem)", speaker="x"),
            item("c2", "hearsay", "took(bob,gem)", speaker="y"),
            item("c3", "hearsay", "took(bob,gem)", speaker="anonymous"),
        ],
        "ideal": [
            ("being named, however often, convicts nobody", lambda r: convicted(r) is None),
            ("his guilt is not believed", lambda r: status(r, "took(bob,gem)") != "believed"),
            ("three accusations count as one", lambda r: r.suspects["bob"].named == 1),
        ],
    },
    # 4. Contradictory claims by one speaker.
    "a speaker who contradicts himself": {
        "culprit": "bob",
        "items": [said("a", "w1", "at(ann,vault,s1)"), said("b", "w1", "at(ann,cafe,s1)")],
        "ideal": [
            ("neither version is believed", lambda r: status(r, "at(ann,vault,s1)") != "believed" and status(r, "at(ann,cafe,s1)") != "believed"),
            ("the contradiction is recognised", lambda r: len(r.contradictions) == 1),
            ("a speaker who says two incompatible things loses credibility", lambda r: standing(r, "w1") == "impeached"),
        ],
    },
    # 5. Repeated hearsay without corroboration.
    "a rumour repeated by four people": {
        "culprit": "ann",
        "items": [WHEN_S1] + [item(f"r{i}", "hearsay", "has_motive(bob)", speaker=who) for i, who in enumerate(("x", "y", "z", "anonymous"))],
        "ideal": [
            ("repetition does not make a motive strong", lambda r: r.suspects["bob"].motive == "weak"),
            ("the rumour is not believed", lambda r: status(r, "has_motive(bob)") == "tentative"),
        ],
    },
    "one claim passed along a chain": {
        "culprit": "ann",
        "items": [said("s1", "x", "at(bob,vault,s1)", origin="w1"), said("s2", "y", "at(bob,vault,s1)", origin="w1"), said("s3", "z", "at(bob,vault,s1)", origin="w1")],
        "ideal": [
            ("three reports of one person's word are not believed", lambda r: status(r, "at(bob,vault,s1)") == "tentative"),
            ("and corroborate nobody", lambda r: r.credibility == {}),
        ],
    },
    # 6. An investigator receiving persuasive false testimony.
    "two friends give the culprit a false alibi": {
        "culprit": "bob",
        "items": [WHEN_S1, TOOL, BOB_HAD_TOOL, BOB_MOTIVE, BOB_VAULT, said("a", "w1", "at(bob,cafe,s1)"), said("b", "w2", "at(bob,cafe,s1)")],
        "ideal": [
            ("the false alibi is not believed", lambda r: status(r, "at(bob,cafe,s1)") != "believed"),
            ("nobody innocent is convicted", lambda r: convicted(r) in (None, "bob")),
            ("he stays the prime suspect", lambda r: r.prime_suspect == "bob"),
            ("two voices against one door record do not clear him: the record is not rejected", lambda r: status(r, "at(bob,vault,s1)") != "rejected"),
        ],
    },
    "two friends' alibi should not be enough to stop a conviction resting on a record": {
        "culprit": "bob",
        "items": [WHEN_S1, TOOL, BOB_HAD_TOOL, BOB_MOTIVE, BOB_VAULT, said("a", "w1", "at(bob,cafe,s1)"), said("b", "w2", "at(bob,cafe,s1)")],
        "ideal": [
            ("the culprit is convicted despite the alibi", lambda r: convicted(r) == "bob"),
        ],
    },
    "a false sighting frames an innocent": {
        # w1 lies. Ann had the tool lawfully and has a motive. Nothing else places her at the vault.
        "culprit": "bob",
        "items": [WHEN_S1, TOOL, ANN_HAD_TOOL, ANN_MOTIVE, said("lie", "w1", "at(ann,vault,s1)")],
        "ideal": [
            ("one person's unchecked word does not convict", lambda r: convicted(r) is None),
        ],
    },
    # 7. Credibility after contradictory hard evidence. (The sequence is tested separately below.)
    "the witness was honestly mistaken once": {
        # w1 is wrong about Bob (refuted by the door record) and right about Ann being in the cafe.
        "culprit": "bob",
        "items": [WHEN_S1, BOB_VAULT, said("a", "w1", "at(bob,cafe,s1)"), said("b", "w1", "at(ann,cafe,s1)")],
        "ideal": [
            ("the mistaken claim is rejected", lambda r: status(r, "at(bob,cafe,s1)") == "rejected"),
            ("an honest mistake does not cost an innocent person a true alibi", lambda r: r.suspects["ann"].opportunity == "alibi"),
        ],
    },
    # 8. Insufficient evidence.
    "a time and a motive": {
        "culprit": "bob",
        "items": [WHEN_S1, BOB_MOTIVE],
        "ideal": [
            ("nobody is convicted", lambda r: convicted(r) is None),
            ("nobody is even the prime suspect", lambda r: r.prime_suspect is None),
            ("his guilt is held open, not believed and not rejected", lambda r: status(r, "took(bob,gem)") == "tentative"),
        ],
    },
    "nothing at all": {
        "culprit": "bob",
        "items": [],
        "ideal": [
            ("no conclusion from no information", lambda r: convicted(r) is None and r.prime_suspect is None and r.beliefs == {} and r.credibility == {}),
        ],
    },
}

# Cases where the frozen rules fall short of the ideal, with the reason. Recorded after the single run.
LIMITS = {
    "lawful access and an ordinary motive":
        "Opportunity, means and motive are each a true record, so the standard is met for Ann. "
        "The rules cannot tell lawful access from guilty access. Known early on as 'wrong but supported'.",
    "one true sighting completes a case against an innocent":
        "A non-suspect witness weighs 2 and belief needs 2, so one unchecked sighting gives strong opportunity.",
    "a false sighting frames an innocent":
        "Same cause as the true sighting: the reasoner has no way to tell them apart, and one voice is enough.",
    "a speaker who contradicts himself":
        "Only hard evidence impeaches. Two incompatible claims from one speaker are held as disputed and the "
        "speaker's standing stays unknown.",
    "two friends' alibi should not be enough to stop a conviction resting on a record":
        "Two voices (2 + 2) hold one record (4) to a draw. Opportunity becomes contested and nobody is convicted: "
        "undecided rather than wrong, but two colluding witnesses can block a true conviction.",
    "the witness was honestly mistaken once":
        "The rules do not separate a mistake from a lie. Once refuted on Bob, w1's word for Ann weighs 1 and "
        "her alibi is no longer believed.",
}


def run(name: str):
    return revise(CASES[name]["items"], ctx())


def shortfalls(name: str) -> list[str]:
    revision = run(name)
    return [description for description, check in CASES[name]["ideal"] if not check(revision)]


# -- contracts ---------------------------------------------------------------------------------


def test_the_rules_under_test_are_the_frozen_ones():
    assert RULES_VERSION == FROZEN_RULES, "the rules changed: re-run the challenge and re-record RESULTS before trusting it"


@pytest.mark.parametrize("name", sorted(CASES))
def test_contract_the_conclusion_does_not_depend_on_the_order_of_arrival(name):
    items = CASES[name]["items"]
    reference = revise(items, ctx())
    orders = itertools.islice(itertools.permutations(items), 24)
    for order in orders:
        again = revise(list(order), ctx())
        assert (again.beliefs, again.suspects, again.prime_suspect, again.contradictions, again.credibility) == (
            reference.beliefs, reference.suspects, reference.prime_suspect, reference.contradictions, reference.credibility)


@pytest.mark.parametrize("name", sorted(CASES))
def test_contract_nobody_is_convicted_without_all_three_legs_and_at_most_one_person_is(name):
    revision = run(name)
    for suspect in SUSPECTS:
        a = revision.suspects[suspect]
        if meets_standard(revision.suspects, suspect):
            assert a.opportunity == "strong" and a.means and a.motive == "strong"
            assert revision.prime_suspect == suspect
    convicted(revision)  # asserts at most one


@pytest.mark.parametrize("name", sorted(CASES))
def test_contract_only_hard_evidence_changes_a_speakers_standing(name):
    """Take the hard evidence away and nobody has a standing: testimony alone never creates one."""
    soft = [i for i in CASES[name]["items"] if i.kind in ("testimony", "hearsay")]
    assert revise(soft, ctx()).credibility == {}
    for voice, seen in run(name).credibility.items():
        for key in seen.refuted:
            assert run(name).beliefs[key].status == "rejected"
        for key in seen.corroborated:
            assert run(name).beliefs[key].status == "believed"


# -- behaviour: the frozen rules reach the ideal -------------------------------------------------


@pytest.mark.parametrize("name", sorted(set(CASES) - set(LIMITS)))
def test_behaviour_reaches_the_ideal(name):
    assert shortfalls(name) == []


def test_behaviour_credibility_follows_the_evidence_step_by_step():
    """7. One witness, four moments. Each line is what the listener holds, then what it should make of w1."""
    alibi_bob = said("a", "w1", "at(bob,cafe,s1)")
    alibi_ann = said("b", "w1", "at(ann,cafe,s1)")
    cafe_cctv = item("cctv", "forensic", "at(bob,cafe,s1)")

    told = revise([alibi_bob, alibi_ann], ctx())
    assert (status(told, "at(bob,cafe,s1)"), status(told, "at(ann,cafe,s1)"), standing(told, "w1")) == ("believed", "believed", None)

    record = revise([alibi_bob, alibi_ann, BOB_VAULT], ctx())  # the door record contradicts the first claim
    assert (status(record, "at(bob,cafe,s1)"), status(record, "at(ann,cafe,s1)"), standing(record, "w1")) == ("rejected", "tentative", "impeached")

    borne_out = revise([alibi_bob, alibi_ann, BOB_VAULT, ANN_CAFE], ctx())  # the till record bears out the second
    assert (status(borne_out, "at(ann,cafe,s1)"), standing(borne_out, "w1")) == ("believed", "impeached")  # believed on the record; w1 stays caught out
    assert borne_out.credibility["w1"].corroborated == ("at(ann,cafe,s1)",) and borne_out.credibility["w1"].refuted == ("at(bob,cafe,s1)",)

    # Hard evidence now appears on w1's side of the first claim too. With records on both sides
    # the claim is no longer refuted, and the impeachment is withdrawn.
    both_sides = revise([alibi_bob, alibi_ann, BOB_VAULT, ANN_CAFE, cafe_cctv], ctx())
    assert standing(both_sides, "w1") == "corroborated" and both_sides.credibility["w1"].refuted == ()


# -- limits: the frozen rules fall short, and this is what they do instead -----------------------


@pytest.mark.parametrize("name", sorted(LIMITS))
@pytest.mark.xfail(strict=True, reason="recorded limitation of rules 2026.11-credibility; see LIMITS")
def test_limit_the_ideal_is_not_reached(name):
    assert shortfalls(name) == []


def test_limit_what_happens_instead():
    """Literal outcomes for each recorded limitation, so that a silent change in either direction is seen."""
    lawful = run("lawful access and an ordinary motive")
    assert convicted(lawful) == "ann" and lawful.suspects["ann"].score == 7  # wrong, and supported

    for name in ("one true sighting completes a case against an innocent", "a false sighting frames an innocent"):
        framed = run(name)
        assert convicted(framed) == "ann" and framed.suspects["ann"].opportunity == "strong"
        assert framed.credibility == {}  # nothing to check the witness against

    twice = run("a speaker who contradicts himself")
    assert (status(twice, "at(ann,vault,s1)"), status(twice, "at(ann,cafe,s1)"), standing(twice, "w1")) == ("disputed", "disputed", None)

    blocked = run("two friends' alibi should not be enough to stop a conviction resting on a record")
    assert convicted(blocked) is None and blocked.suspects["bob"].opportunity == "contested" and blocked.prime_suspect == "bob"

    mistaken = run("the witness was honestly mistaken once")
    assert standing(mistaken, "w1") == "impeached" and mistaken.suspects["ann"].opportunity == "none"
    assert status(mistaken, "at(ann,cafe,s1)") == "tentative"


# -- the record ----------------------------------------------------------------------------------

# name -> the ideal expectations the frozen rules did not meet. Written down after the single run.
RESULTS = {
    "a false sighting frames an innocent": ["one person's unchecked word does not convict"],
    "a rumour repeated by four people": [],
    "a speaker who contradicts himself": ["a speaker who says two incompatible things loses credibility"],
    "a time and a motive": [],
    "lawful access and an ordinary motive": ["an innocent person is not convicted because the culprit left no records"],
    "lawful access without motive": [],
    "many accusers and a motive": [],
    "nothing at all": [],
    "one claim passed along a chain": [],
    "one true sighting completes a case against an innocent": ["a single unchecked witness is not enough for the opportunity leg"],
    "the witness was honestly mistaken once": ["an honest mistake does not cost an innocent person a true alibi"],
    "two friends give the culprit a false alibi": [],
    "two friends' alibi should not be enough to stop a conviction resting on a record": ["the culprit is convicted despite the alibi"],
}


def test_the_recorded_results_are_the_actual_results():
    actual = {name: shortfalls(name) for name in sorted(CASES)}
    assert actual == RESULTS
    assert sorted(name for name, missed in actual.items() if missed) == sorted(LIMITS)
    met = sum(1 for missed in actual.values() if not missed)
    assert (met, len(actual)) == (7, 13)  # seven of thirteen cases reach every ideal expectation
