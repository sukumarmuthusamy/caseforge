"""Reasoning judged against expectations written by hand, in a world that is not a bundled scenario.

Every expected value below was worked out on paper from the published weights
(forensic 5, record 4, testimony 2, a suspect's word about their own
whereabouts or about the time of the crime 1, hearsay 1 and never stacking;
believed at a net of 2; opportunity 3, means 2, motive 2, alibi -4; the
standard needs all three legs and a lead of 3). None of it is produced by
calling the reasoner, so a change in the rules shows up here as a failure.

Each case also says who really did it. `verdict` records how the reasoner's
conclusion relates to that:

    right      the standard is met for the real culprit
    undecided  the standard is met for nobody
    wrong      the standard is met for an innocent person

A "wrong" case is not a bug in the test. It is a documented limit: the rules
can be satisfied by evidence that is true, incomplete and misleading. Meeting
the standard of proof means "conforms to these rules", never "is true".
"""

from __future__ import annotations

import pytest

from caseforge.reasoning import Item, ReasoningContext, meets_standard, revise

ZONES = {"vault": "inside", "strongroom_door": "inside", "badge_desk": "desk", "cafe": "cafe"}
SUSPECTS = ("ann", "bob", "cy")


def ctx(hearsay_weight: int = 1) -> ReasoningContext:
    return ReasoningContext(zones=ZONES, suspects=SUSPECTS, crime_location="vault", crime_object="gem", hearsay_weight=hearsay_weight)


def item(item_id: str, kind: str, *asserts: str, speaker: str | None = None) -> Item:
    from caseforge.models import Proposition

    return Item(id=item_id, kind=kind, speaker=speaker, asserts=tuple(Proposition.parse(a) for a in asserts))


# Building blocks. w1 and w2 are witnesses who are not suspects.
WHEN_S1 = item("when", "record", "crime_at(vault,s1)")
ANN_SEEN = item("seen", "testimony", "at(ann,vault,s1)", speaker="w1")
ANN_SEEN_TOO = item("seen2", "testimony", "at(ann,strongroom_door,s1)", speaker="w2")  # same zone as the vault
ANN_SEEN_AGAIN = item("seen3", "testimony", "at(ann,vault,s1)", speaker="w1")  # the same witness, repeating herself
ANN_CAFE = item("till", "record", "at(ann,cafe,s1)")
BOB_VAULT = item("door", "record", "at(bob,vault,s1)")
BOB_VAULT_TOO = item("cam", "record", "at(bob,strongroom_door,s1)")
BOB_DENIES = item("denial", "testimony", "at(bob,cafe,s1)", speaker="bob")
BOB_FRIEND = item("friend", "testimony", "at(bob,cafe,s1)", speaker="w2")
TOOL = item("marks", "forensic", "crime_used(crowbar)")
BOB_HAD_TOOL = item("hire", "record", "had(bob,crowbar,s1)")
ANN_HAD_TOOL_LATER = item("hire2", "record", "had(ann,crowbar,s2)")
BOB_MOTIVE = item("debt", "record", "has_motive(bob)")
ANN_MOTIVE = item("grudge", "record", "has_motive(ann)")
ANN_CARD = item("reader", "record", "card_used(k1,vault,s1)", "card_holder(k1,ann)")

CASES = [
    {
        "name": "a record outweighs a lone witness",
        "items": [WHEN_S1, ANN_SEEN, ANN_CAFE],
        "status": {"at(ann,vault,s1)": "rejected", "at(ann,cafe,s1)": "believed"},
        "contradictions": 1,
        "suspects": {"ann": {"opportunity": "alibi", "score": -4}},
        "prime": None, "standard": None, "culprit": "bob", "verdict": "undecided",
    },
    {
        "name": "two independent witnesses hold a record to a draw",
        "items": [WHEN_S1, ANN_SEEN, ANN_SEEN_TOO, ANN_CAFE],
        "status": {"at(ann,vault,s1)": "disputed", "at(ann,cafe,s1)": "disputed"},
        "contradictions": 2,
        "suspects": {"ann": {"opportunity": "contested", "score": 0}},
        "prime": None, "standard": None, "culprit": "bob", "verdict": "undecided",
    },
    {
        "name": "one voice counts once however often it speaks",
        "items": [WHEN_S1, ANN_SEEN, ANN_SEEN_AGAIN, ANN_CAFE],
        "status": {"at(ann,vault,s1)": "rejected"},
        "contradictions": 1,
        "suspects": {"ann": {"opportunity": "alibi"}},
        "prime": None, "standard": None, "culprit": "bob", "verdict": "undecided",
    },
    {
        "name": "a suspect's own alibi does not dent a record",
        "items": [WHEN_S1, BOB_VAULT, BOB_DENIES, TOOL, BOB_HAD_TOOL, BOB_MOTIVE],
        "status": {"at(bob,vault,s1)": "believed", "at(bob,cafe,s1)": "rejected"},
        "contradictions": 1,
        "suspects": {"bob": {"opportunity": "strong", "means": True, "motive": "strong", "score": 7}},
        "prime": "bob", "standard": "bob", "culprit": "bob", "verdict": "right",
    },
    {
        "name": "an alibi witness plus the denial contest a single record",
        "items": [WHEN_S1, BOB_VAULT, BOB_DENIES, BOB_FRIEND, TOOL, BOB_HAD_TOOL, BOB_MOTIVE],
        "status": {"at(bob,vault,s1)": "disputed"},  # 4 against 2 + 1: a net of 1
        "contradictions": 1,
        "suspects": {"bob": {"opportunity": "contested", "means": True, "motive": "strong", "score": 4}},
        "prime": "bob", "standard": None, "culprit": "bob", "verdict": "undecided",
    },
    {
        "name": "a second independent record settles the contested alibi",
        "items": [WHEN_S1, BOB_VAULT, BOB_VAULT_TOO, BOB_DENIES, BOB_FRIEND, TOOL, BOB_HAD_TOOL, BOB_MOTIVE],
        "status": {"at(bob,vault,s1)": "believed", "at(bob,cafe,s1)": "rejected"},
        "contradictions": 2,
        "suspects": {"bob": {"opportunity": "strong", "score": 7}},
        "prime": "bob", "standard": "bob", "culprit": "bob", "verdict": "right",
    },
    {
        "name": "custody of the tool counts only at the time of the crime",
        "items": [WHEN_S1, TOOL, ANN_HAD_TOOL_LATER, BOB_HAD_TOOL],
        "status": {"crime_used(crowbar)": "believed", "had(ann,crowbar,s2)": "believed"},
        "contradictions": 0,
        "suspects": {"ann": {"means": False, "score": 0}, "bob": {"means": True, "score": 2}},
        "prime": None, "standard": None, "culprit": "bob", "verdict": "undecided",
    },
    {
        "name": "without a time for the crime nobody has opportunity or means",
        "items": [BOB_VAULT, TOOL, BOB_HAD_TOOL, BOB_MOTIVE],
        "status": {"at(bob,vault,s1)": "believed"},
        "contradictions": 0,
        "suspects": {"bob": {"opportunity": "none", "means": False, "motive": "strong", "score": 2}},
        "prime": None, "standard": None, "culprit": "bob", "verdict": "undecided",
    },
    {
        "name": "allegations alone never amount to proof",
        "items": [item("a1", "testimony", "took(ann,gem)", speaker="w1"), item("a2", "testimony", "took(ann,gem)", speaker="w2"),
                  item("a3", "hearsay", "took(ann,gem)", speaker="anonymous")],
        "status": {"took(ann,gem)": "tentative"},
        "contradictions": 0,
        "suspects": {"ann": {"named": 2, "score": 2, "opportunity": "none"}},  # 2 + 2 + 1, capped at 2
        "prime": None, "standard": None, "culprit": "bob", "verdict": "undecided",
    },
    {
        "name": "rumors do not stack",
        "items": [item("r1", "hearsay", "has_motive(bob)", speaker="anonymous"), item("r2", "hearsay", "has_motive(bob)", speaker="anonymous"),
                  item("r3", "hearsay", "has_motive(bob)", speaker="x")],
        "status": {"has_motive(bob)": "tentative"},
        "contradictions": 0,
        "suspects": {"bob": {"motive": "weak", "score": 1}},
        "prime": None, "standard": None, "culprit": "bob", "verdict": "undecided",
    },
    {
        "name": "a motive known only from a rumor leaves the case unproved",
        "items": [WHEN_S1, BOB_VAULT, TOOL, BOB_HAD_TOOL, item("r1", "hearsay", "has_motive(bob)", speaker="anonymous")],
        "status": {"has_motive(bob)": "tentative"},
        "contradictions": 0,
        "suspects": {"bob": {"opportunity": "strong", "means": True, "motive": "weak", "score": 6}},
        "prime": "bob", "standard": None, "culprit": "bob", "verdict": "undecided",
    },
    {
        "name": "two strong suspects without a clear lead",
        "items": [WHEN_S1, BOB_VAULT, TOOL, BOB_HAD_TOOL, BOB_MOTIVE, item("ann_door", "record", "at(ann,vault,s1)"), ANN_MOTIVE],
        "status": {},
        "contradictions": 0,
        "suspects": {"bob": {"score": 7}, "ann": {"score": 5, "means": False}},  # a lead of 2, and 3 is required
        "prime": "bob", "standard": None, "culprit": "bob", "verdict": "undecided",
    },
    {
        # Everything here is a true record. It is simply not the whole story: the card was copied
        # (see the next case), and nobody has looked at the reader yet.
        "name": "true but incomplete records convict the card's owner",
        "items": [WHEN_S1, ANN_CARD, ANN_MOTIVE],
        "status": {"at(ann,vault,s1)": "believed"},  # derived by R1, weight 2
        "contradictions": 0,
        "suspects": {"ann": {"opportunity": "strong", "means": True, "motive": "strong", "score": 7}},
        "prime": "ann", "standard": "ann", "culprit": "bob", "verdict": "wrong",
    },
    {
        "name": "the copied card moves the case to whoever was at the encoder",
        "items": [WHEN_S1, ANN_CARD, ANN_MOTIVE, item("chip", "forensic", "card_cloned(k1)"),
                  item("encoder", "record", "card_written(k1,badge_desk,s0)"), item("rota", "record", "at(bob,badge_desk,s0)"), BOB_MOTIVE],
        "status": {"at(ann,vault,s1)": "withdrawn", "could_use(bob,k1)": "believed", "at(bob,vault,s1)": "believed"},
        "contradictions": 0,
        "suspects": {"ann": {"opportunity": "none", "means": False, "score": 2}, "bob": {"opportunity": "strong", "means": True, "score": 7}},
        "prime": "bob", "standard": "bob", "culprit": "bob", "verdict": "right",
    },
    {
        # A witness who is wrong about the evening, and no physical record of the time at all.
        "name": "a mistaken witness fixes the wrong evening and an innocent keyholder fits it",
        "items": [item("guard", "testimony", "crime_at(vault,s2)", speaker="w1"), item("door2", "record", "at(ann,vault,s2)"),
                  TOOL, ANN_HAD_TOOL_LATER, ANN_MOTIVE, BOB_HAD_TOOL, BOB_VAULT, BOB_MOTIVE],
        "status": {"crime_at(vault,s2)": "believed"},
        "contradictions": 0,
        "suspects": {"ann": {"opportunity": "strong", "means": True, "score": 7}, "bob": {"opportunity": "none", "means": False, "score": 2}},
        "prime": "ann", "standard": "ann", "culprit": "bob", "verdict": "wrong",
    },
    {
        "name": "a suspect's word about the time only puts the witness in doubt",
        "items": [item("guard", "testimony", "crime_at(vault,s2)", speaker="w1"), item("ann_says", "testimony", "crime_at(vault,s1)", speaker="ann"),
                  item("door2", "record", "at(ann,vault,s2)"), TOOL, ANN_HAD_TOOL_LATER, ANN_MOTIVE],
        "status": {"crime_at(vault,s2)": "disputed", "crime_at(vault,s1)": "disputed"},  # 2 against 1
        "contradictions": 1,
        "suspects": {"ann": {"opportunity": "none", "means": False, "score": 2}},
        "prime": None, "standard": None, "culprit": "bob", "verdict": "undecided",
    },
    {
        "name": "a physical record of the time overturns the witness and the case with it",
        "items": [item("guard", "testimony", "crime_at(vault,s2)", speaker="w1"), item("logger", "record", "crime_at(vault,s1)"),
                  item("door2", "record", "at(ann,vault,s2)"), TOOL, ANN_HAD_TOOL_LATER, ANN_MOTIVE, BOB_HAD_TOOL, BOB_VAULT, BOB_MOTIVE],
        "status": {"crime_at(vault,s1)": "believed", "crime_at(vault,s2)": "rejected"},
        "contradictions": 1,
        "suspects": {"ann": {"opportunity": "none", "means": False, "score": 2}, "bob": {"opportunity": "strong", "means": True, "score": 7}},
        "prime": "bob", "standard": "bob", "culprit": "bob", "verdict": "right",
    },
]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_hand_worked_case(case):
    result = revise(case["items"], ctx())
    for key, status in case["status"].items():
        assert result.beliefs[key].status == status, key
    assert len(result.contradictions) == case["contradictions"], result.contradictions
    for suspect, expected in case["suspects"].items():
        actual = result.suspects[suspect]
        for field, value in expected.items():
            assert getattr(actual, field) == value, f"{suspect}.{field}"
    assert result.prime_suspect == case["prime"]
    convicted = [s for s in SUSPECTS if meets_standard(result.suspects, s)]
    assert convicted == ([case["standard"]] if case["standard"] else [])

    # How the conclusion relates to what actually happened is a separate question.
    verdict = "undecided" if not convicted else "right" if convicted[0] == case["culprit"] else "wrong"
    assert verdict == case["verdict"]


def test_the_cases_include_convictions_of_the_innocent():
    """Kept explicit so nobody reads a green suite as "the reasoner finds the truth"."""
    wrong = [c["name"] for c in CASES if c["verdict"] == "wrong"]
    assert len(wrong) == 2
    assert sum(1 for c in CASES if c["verdict"] == "right") == 4
    assert sum(1 for c in CASES if c["verdict"] == "undecided") == 11


def test_order_of_arrival_does_not_change_the_conclusion():
    case = CASES[-1]
    forward = revise(case["items"], ctx())
    backward = revise(list(reversed(case["items"])), ctx())
    assert forward.beliefs == backward.beliefs and forward.suspects == backward.suspects


def test_what_an_agent_believes_depends_on_how_it_weighs_rumor():
    """The same items, two readers: one is personally convinced, the reference standard is not."""
    items = [WHEN_S1, BOB_VAULT, TOOL, BOB_HAD_TOOL, item("r1", "hearsay", "has_motive(bob)", speaker="anonymous")]
    careful, credulous = revise(items, ctx(1)), revise(items, ctx(2))
    assert careful.beliefs["has_motive(bob)"].status == "tentative" and careful.suspects["bob"].motive == "weak"
    assert credulous.beliefs["has_motive(bob)"].status == "believed" and credulous.suspects["bob"].motive == "strong"
    assert not meets_standard(careful.suspects, "bob") and meets_standard(credulous.suspects, "bob")


def test_what_an_agent_believes_depends_on_what_it_holds():
    """Two agents, the same rules, different records: opposite conclusions about Ann."""
    sees_the_card = revise([WHEN_S1, ANN_CARD, ANN_MOTIVE], ctx())
    sees_the_till = revise([WHEN_S1, ANN_CARD, ANN_MOTIVE, ANN_CAFE], ctx())
    assert sees_the_card.beliefs["at(ann,vault,s1)"].status == "believed"
    assert sees_the_till.beliefs["at(ann,vault,s1)"].status == "rejected"  # derived 2 against a record's 4
    assert sees_the_till.suspects["ann"].opportunity == "alibi" and not meets_standard(sees_the_till.suspects, "ann")


def test_belief_revision_is_not_monotonic():
    """A believed proposition can be lost again: nothing is locked in by having been believed once."""
    steps = [
        ([ANN_SEEN], "believed"),
        ([ANN_SEEN, ANN_CAFE], "rejected"),
        ([ANN_SEEN, ANN_CAFE, ANN_SEEN_TOO], "disputed"),
        ([ANN_SEEN, ANN_CAFE, ANN_SEEN_TOO, item("door", "record", "at(ann,vault,s1)")], "believed"),
    ]
    assert [revise(items, ctx()).beliefs["at(ann,vault,s1)"].status for items, _ in steps] == [status for _, status in steps]


# -- credibility: what can be checked of a speaker's word --------------------------------------
# Worked by hand like everything above. w1 and w2 are witnesses, not suspects: their word weighs 2.


def said(item_id: str, speaker: str, proposition: str, origin: str | None = None) -> Item:
    from caseforge.models import Proposition

    return Item(id=item_id, kind="testimony", speaker=speaker, asserts=(Proposition.parse(proposition),), origin=origin)


def standing(revision) -> dict:
    return {voice: (c.standing, c.refuted, c.corroborated) for voice, c in revision.credibility.items()}


def test_a_record_refutes_a_claim_and_the_speakers_other_word_is_discounted():
    """w1 says Bob was in the cafe (2) against the door record (4): rejected, and refuted.

    w1 also says Ann was at the vault. Alone that would be believed at 2. From a
    speaker caught out it weighs 1: tentative.
    """
    alone = revise([said("a", "w1", "at(ann,vault,s1)")], ctx())
    assert alone.beliefs["at(ann,vault,s1)"].status == "believed" and alone.credibility == {}

    caught = revise([BOB_VAULT, said("a", "w1", "at(ann,vault,s1)"), said("b", "w1", "at(bob,cafe,s1)")], ctx())
    assert standing(caught) == {"w1": ("impeached", ("at(bob,cafe,s1)",), ())}
    assert (caught.beliefs["at(bob,cafe,s1)"].support, caught.beliefs["at(bob,cafe,s1)"].contra, caught.beliefs["at(bob,cafe,s1)"].status) == (2, 4, "rejected")
    assert (caught.beliefs["at(ann,vault,s1)"].support, caught.beliefs["at(ann,vault,s1)"].status) == (1, "tentative")
    # The record is not weakened by the claim it refuted being weighed at full value: 4 against 2.
    assert (caught.beliefs["at(bob,vault,s1)"].support, caught.beliefs["at(bob,vault,s1)"].contra) == (4, 2)


def test_enough_voices_hold_a_record_to_a_draw_and_then_nobody_is_refuted():
    """Two independent witnesses, 2 + 2, against one record, 4. Disputed, so neither witness is caught out."""
    revision = revise([WHEN_S1, ANN_SEEN, ANN_SEEN_TOO, ANN_CAFE], ctx())
    assert revision.beliefs["at(ann,vault,s1)"].status == "disputed" and revision.credibility == {}


def test_testimony_does_not_corroborate_or_impeach_testimony():
    agree = revise([ANN_SEEN, ANN_SEEN_TOO], ctx())
    assert agree.beliefs["at(ann,vault,s1)"].support == 4 and agree.credibility == {}
    disagree = revise([ANN_SEEN, said("c", "w2", "at(ann,cafe,s1)")], ctx())
    assert disagree.beliefs["at(ann,vault,s1)"].status == "disputed" and disagree.credibility == {}


def test_corroboration_is_noted_and_earns_no_extra_weight():
    """A record (4) and a witness (2) say the same: 6, exactly their sum. The witness is corroborated."""
    revision = revise([said("a", "w1", "at(bob,vault,s1)"), BOB_VAULT], ctx())
    assert standing(revision) == {"w1": ("corroborated", (), ("at(bob,vault,s1)",))}
    assert revision.beliefs["at(bob,vault,s1)"].support == 6
    # Being right once does not make the rest of what w1 says count for more than anyone's word: 2.
    more = revise([said("a", "w1", "at(bob,vault,s1)"), BOB_VAULT, said("b", "w1", "at(ann,vault,s1)")], ctx())
    assert more.beliefs["at(ann,vault,s1)"].support == 2


def test_a_statement_passed_on_is_the_first_speakers_voice_heard_once():
    """w1's claim arrives directly (2), through x and through y. Still w1 alone: 2, not 4 or 6."""
    direct = said("a", "w1", "at(ann,vault,s1)")
    via_x = said("b", "x", "at(ann,vault,s1)", origin="w1")
    via_y = said("c", "y", "at(ann,vault,s1)", origin="w1")
    assert revise([direct, via_x, via_y], ctx()).beliefs["at(ann,vault,s1)"].support == 2
    # Heard only second hand it weighs as hearsay, 1, however many people repeat it.
    second_hand = revise([via_x, via_y], ctx())
    assert (second_hand.beliefs["at(ann,vault,s1)"].support, second_hand.beliefs["at(ann,vault,s1)"].status) == (1, "tentative")
    # An agent that gives hearsay 2 is convinced by the same report.
    assert revise([via_x, via_y], ctx(2)).beliefs["at(ann,vault,s1)"].status == "believed"
    # If the report is refuted, it is w1 who is caught out, not the people who repeated it.
    refuted = revise([via_x, ANN_CAFE], ctx())
    assert standing(refuted) == {"w1": ("impeached", ("at(ann,vault,s1)",), ())}


def test_what_an_agent_saw_itself_outweighs_what_it_is_told():
    """An observation weighs 4, like a record. A contrary statement (2) is rejected and its speaker caught out."""
    from caseforge.models import Proposition

    seen = Item(id="O1", kind="observation", speaker="me", asserts=(Proposition.parse("at(ann,cafe,s1)"),))
    revision = revise([seen, ANN_SEEN], ctx())
    assert (revision.beliefs["at(ann,cafe,s1)"].support, revision.beliefs["at(ann,cafe,s1)"].status) == (4, "believed")
    assert revision.beliefs["at(ann,vault,s1)"].status == "rejected"
    assert standing(revision) == {"w1": ("impeached", ("at(ann,vault,s1)",), ())}


def test_a_rival_time_for_the_crime_is_refuted_by_a_record_of_the_real_one():
    """w1 says it happened on s2 (2); the alarm record says s1 (4). Refuted, and w1's alibi for Ann drops to 1."""
    revision = revise([WHEN_S1, said("a", "w1", "crime_at(vault,s2)"), said("b", "w1", "at(ann,cafe,s1)")], ctx())
    assert standing(revision) == {"w1": ("impeached", ("crime_at(vault,s2)",), ())}
    assert revision.beliefs["crime_at(vault,s1)"].status == "believed"
    assert (revision.beliefs["at(ann,cafe,s1)"].support, revision.beliefs["at(ann,cafe,s1)"].status) == (1, "tentative")
    assert revision.suspects["ann"].opportunity == "none"  # an alibi from an impeached witness is not an alibi


# -- one voice, several places in one zone --------------------------------------------------
# Presence is judged per zone. The vault and the strongroom door are one zone ("inside"), so
# "she was at the vault" and "she was at the strongroom door" are the same thing said twice.


def test_one_voice_naming_two_places_in_one_zone_is_still_one_voice():
    """w1 says Ann was at the vault (2) against the till record (4): rejected, w1 caught out.

    w1 then adds that she was at the strongroom door. No new witness, no new
    evidence: still 2 against 4, both versions rejected, w1 still impeached.
    Before the fix the zone summed to 4, the record was held to a draw and the
    impeachment disappeared.
    """
    first = revise([ANN_CAFE, said("a", "w1", "at(ann,vault,s1)")], ctx())
    assert standing(first) == {"w1": ("impeached", ("at(ann,vault,s1)",), ())}

    both = revise([ANN_CAFE, said("a", "w1", "at(ann,vault,s1)"), said("b", "w1", "at(ann,strongroom_door,s1)")], ctx())
    for key in ("at(ann,vault,s1)", "at(ann,strongroom_door,s1)"):
        assert (both.beliefs[key].support, both.beliefs[key].contra, both.beliefs[key].status) == (2, 4, "rejected")
    assert (both.beliefs["at(ann,cafe,s1)"].support, both.beliefs["at(ann,cafe,s1)"].contra, both.beliefs["at(ann,cafe,s1)"].status) == (4, 2, "believed")
    assert standing(both) == {"w1": ("impeached", ("at(ann,strongroom_door,s1)", "at(ann,vault,s1)"), ())}
    # Every statement is still listed as what the belief rests on (in order of the place named).
    assert both.beliefs["at(ann,vault,s1)"].evidence == ("b", "a") and both.beliefs["at(ann,cafe,s1)"].against == ("b", "a")


def test_independent_witnesses_at_two_places_in_one_zone_still_count_separately():
    """w1 at the vault, w2 at the strongroom door: two people, 2 + 2. A third statement by w1 adds nothing."""
    two = revise([ANN_CAFE, ANN_SEEN, ANN_SEEN_TOO], ctx())
    assert (two.beliefs["at(ann,vault,s1)"].support, two.beliefs["at(ann,vault,s1)"].status) == (4, "disputed")
    three = revise([ANN_CAFE, ANN_SEEN, ANN_SEEN_TOO, said("b", "w1", "at(ann,strongroom_door,s1)")], ctx())
    assert (three.beliefs["at(ann,vault,s1)"].support, three.beliefs["at(ann,vault,s1)"].status) == (4, "disputed")
    assert three.credibility == {}


def test_hard_records_at_two_places_in_one_zone_still_add_up():
    """A door record and a camera record are two systems: 4 + 4, whatever one witness says elsewhere (2)."""
    revision = revise([BOB_VAULT, BOB_VAULT_TOO, BOB_FRIEND], ctx())
    assert (revision.beliefs["at(bob,vault,s1)"].support, revision.beliefs["at(bob,vault,s1)"].contra) == (8, 2)
    # A witness and a record in the same zone are different sources too: 2 + 4.
    mixed = revise([said("a", "w1", "at(bob,strongroom_door,s1)"), BOB_VAULT], ctx())
    assert mixed.beliefs["at(bob,vault,s1)"].support == 6


def test_a_relay_naming_another_place_in_the_zone_is_the_same_voice():
    """w1 says the vault directly (2); x passes on w1 saying the strongroom door (1). One voice, its best weight: 2."""
    direct = said("a", "w1", "at(ann,vault,s1)")
    via_x = said("b", "x", "at(ann,strongroom_door,s1)", origin="w1")
    via_y = said("c", "y", "at(ann,vault,s1)", origin="w1")
    assert revise([direct, via_x], ctx()).beliefs["at(ann,vault,s1)"].support == 2
    # Second hand only, by two routes and about two places: 1, not 2, and not believed.
    second_hand = revise([via_x, via_y], ctx())
    assert (second_hand.beliefs["at(ann,vault,s1)"].support, second_hand.beliefs["at(ann,vault,s1)"].status) == (1, "tentative")


def test_rumours_about_two_places_in_one_zone_do_not_stack():
    """Hearsay never adds up. Two anonymous notes, one per doorway of the same zone, are still 1."""
    notes = [item("n1", "hearsay", "at(ann,vault,s1)", speaker="x"), item("n2", "hearsay", "at(ann,strongroom_door,s1)", speaker="y")]
    revision = revise(notes, ctx())
    assert (revision.beliefs["at(ann,vault,s1)"].support, revision.beliefs["at(ann,vault,s1)"].status) == (1, "tentative")


def test_one_voice_cannot_place_someone_where_a_card_was_copied_by_saying_it_twice():
    """R3 needs a net of 2 for presence where the copy was written.

    w1 names the badge desk and its window (one zone): 2. w2 says the cafe: 2.
    Net 0, so nobody "could use" the copy. With a third, independent witness
    at the window it is 4 against 2 and the derivation holds.
    """
    zones = dict(ZONES, desk_window="desk")
    context = ReasoningContext(zones=zones, suspects=SUSPECTS, crime_location="vault", crime_object="gem")
    written = item("enc", "record", "card_written(k1,badge_desk,s0)")
    elsewhere = said("c", "w2", "at(ann,cafe,s0)")
    one_voice = revise([written, said("a", "w1", "at(ann,badge_desk,s0)"), said("b", "w1", "at(ann,desk_window,s0)"), elsewhere], context)
    assert "could_use(ann,k1)" not in one_voice.beliefs
    two_voices = revise([written, said("a", "w1", "at(ann,badge_desk,s0)"), said("b", "w3", "at(ann,desk_window,s0)"), elsewhere], context)
    assert two_voices.beliefs["could_use(ann,k1)"].status == "believed"
