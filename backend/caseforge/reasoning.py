"""Belief revision: from a set of information items to a belief table.

Pure and deterministic. The input is whatever an agent has to go on (evidence
records, what it saw for itself, what it was told, and active public claims);
the output is a status per proposition, an assessment per suspect, the
contradictions present, and what could be checked of each speaker's word.

Nothing here knows the truth, and nothing here is specific to one scenario:
the rules speak only about places, times, cards, tools, motive and allegations.

Rules that are general (any case with a place, a time and suspects):
presence by zone, competing times for the crime, opportunity, motive,
allegations, the standard of proof. Rules that belong to one kind of means:
R1 to R4 (a card opens a door, and may have been copied) and R5 (the crime
needed a tool, and somebody had custody of it at the time). A case uses the
ones its evidence speaks to.

Kinds of information, and what each is worth:

    forensic      5   adds up with other hard evidence
    record        4   adds up
    observation   4   adds up; what the reasoning agent saw for itself
    testimony     2   one voice counts once, however often it is heard and
                      whichever spot in a zone it names
                  1   when the speaker has a stake (a suspect on their own
                      whereabouts or on when it happened), when the speaker was
                      caught out on something else, or when the words reach
                      the agent second hand and it weighs hearsay at 1
    hearsay       1   never adds up (an agent's disposition may say 2)

Credibility. A spoken claim is *refuted* for an agent when hard evidence it
holds supports a conflicting statement (another place for the same person and
time, another time for the crime at the same place), none supports the claim,
and the agent, weighing everything at face value, rejects it. It is
*corroborated* when hard evidence supports it, none conflicts, and the agent
believes it. Hard evidence is required on either side: two people saying the
same thing do not corroborate each other, and one speaker's word never
impeaches another's. Enough voices can still hold a single record to a draw,
and then nobody is refuted.

A speaker with one refuted claim is *impeached*: whatever else that speaker
says is no longer believed on their word alone. The refuted claim itself is
weighed as before, since the evidence against it has already been counted
once. Corroboration earns no extra weight for the same reason. All of this is
relative to what the agent holds, so two agents can judge the same speaker
differently, and neither judgment looks at what really happened.

So credibility is two things. Of a claim: refuted, corroborated, or unchecked.
Of a speaker, as one listener sees them: impeached, corroborated, or unknown.
It is never a number and never global.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .models import BeliefEntry, Credibility, Derivation, Proposition, SuspectAssessment

# Identifies the rule set. Challenge results (tests/test_challenge.py) are recorded
# against it; change it whenever a weight or a rule in this module changes.
RULES_VERSION = "2026.11-voices"

KIND_WEIGHT = {"forensic": 5, "record": 4, "observation": 4, "testimony": 2}
SOLID_KINDS = ("forensic", "record", "observation")  # hard evidence: independent of anybody's say-so
SELF_SERVING_TESTIMONY_WEIGHT = 1
IMPEACHED_TESTIMONY_WEIGHT = 1  # below BELIEVE_AT: never enough on its own
DERIVED_WEIGHT = 2
BELIEVE_AT = 2  # net weight needed to hold a proposition as believed
PROOF_MARGIN = 3  # lead the top suspect needs over every other suspect
PRIME_MINIMUM = 3  # score below which nobody is called the prime suspect
NAMED_CAP = 2

OPPORTUNITY_POINTS = {"strong": 3, "weak": 1, "none": 0, "contested": 0, "alibi": -4}
MOTIVE_POINTS = {"strong": 2, "weak": 1, "none": 0}
MEANS_POINTS = 2


@dataclass(frozen=True)
class Item:
    """One unit of information: an evidence record, an observation, a statement or a public claim."""

    id: str
    kind: str  # forensic | record | observation | testimony | hearsay
    speaker: str | None
    asserts: tuple[Proposition, ...]
    origin: str | None = None  # testimony passed on by `speaker`: whose word it is

    @property
    def voice(self) -> str:
        """Whose word a piece of testimony is, however it travelled."""
        return self.origin or self.speaker or self.id


@dataclass(frozen=True)
class ReasoningContext:
    zones: Mapping[str, str]  # location id -> zone id
    suspects: tuple[str, ...]
    crime_location: str
    crime_object: str
    hearsay_weight: int = 1


@dataclass
class Revision:
    beliefs: dict[str, BeliefEntry]
    suspects: dict[str, SuspectAssessment]
    prime_suspect: str | None
    contradictions: list[str]
    credibility: dict[str, Credibility] = field(default_factory=dict)  # speaker -> what could be checked


@dataclass
class _Agg:
    """Aggregated direct support for one proposition."""

    prop: Proposition
    solid: int = 0  # records and forensics add up: they are independent systems
    by_speaker: dict[str, int] = field(default_factory=dict)  # one voice counts once
    hearsay: int = 0  # rumors never stack
    ids: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.solid + sum(self.by_speaker.values()) + self.hearsay


def _together(aggs: Iterable[_Agg]) -> int:
    """Direct support for one hypothesis that several propositions express.

    Presence is judged by zone, so "at the vault" and "at the vault door" are
    the same hypothesis. The rules for one proposition carry over unchanged:
    hard evidence adds up, each voice counts once at its best weight, and
    hearsay counts once. Without this a speaker could vote twice by naming two
    spots in one zone.
    """
    solid = 0
    voices: dict[str, int] = {}
    hearsay = 0
    for agg in aggs:
        solid += agg.solid
        for voice, weight in agg.by_speaker.items():
            voices[voice] = max(voices.get(voice, 0), weight)
        hearsay = max(hearsay, agg.hearsay)
    return solid + sum(voices.values()) + hearsay


Refuted = Mapping[str, frozenset[str]]  # impeached voice -> the claims it was caught on


def _weight(item: Item, prop: Proposition, ctx: ReasoningContext, refuted: Refuted | None = None) -> int:
    if item.kind == "hearsay":
        return ctx.hearsay_weight
    if item.kind == "testimony":
        weight = KIND_WEIGHT["testimony"]
        if item.voice in ctx.suspects:
            # A suspect has a stake in where they were, and in when it happened:
            # the time decides who had the opportunity.
            speaks_of_self = prop.predicate == "at" and item.voice == prop.args[0]
            if speaks_of_self or prop.predicate == "crime_at":
                weight = SELF_SERVING_TESTIMONY_WEIGHT
        if item.origin is not None:
            weight = min(weight, ctx.hearsay_weight)  # heard second hand
        if refuted and item.voice in refuted and prop.key not in refuted[item.voice]:
            weight = min(weight, IMPEACHED_TESTIMONY_WEIGHT)  # caught out on something else
        return weight
    return KIND_WEIGHT[item.kind]


def assess_speakers(ordered: list[Item], ctx: ReasoningContext, beliefs: Mapping[str, BeliefEntry]) -> dict[str, Credibility]:
    """Check every spoken claim against the hard evidence among the items.

    `beliefs` is the table computed with every speaker taken at face value, so
    the verdicts do not depend on the discounts they lead to.
    """
    solid: dict[str, int] = {}
    where: dict[tuple[str, str], dict[str, int]] = {}  # (person, slot) -> zone -> hard weight
    when: dict[str, dict[str, int]] = {}  # location -> slot -> hard weight
    for item in ordered:
        if item.kind not in SOLID_KINDS:
            continue
        for prop in item.asserts:
            weight = KIND_WEIGHT[item.kind]
            solid[prop.key] = solid.get(prop.key, 0) + weight
            if prop.predicate == "at":
                zones = where.setdefault((prop.args[0], prop.args[2]), {})
                zone = ctx.zones.get(prop.args[1], prop.args[1])
                zones[zone] = zones.get(zone, 0) + weight
            elif prop.predicate == "crime_at":
                slots = when.setdefault(prop.args[0], {})
                slots[prop.args[1]] = slots.get(prop.args[1], 0) + weight

    refuted: dict[str, set[str]] = {}
    corroborated: dict[str, set[str]] = {}
    for item in ordered:
        if item.kind != "testimony":
            continue
        for prop in item.asserts:
            if prop.predicate == "at":
                options = where.get((prop.args[0], prop.args[2]), {})
                mine = ctx.zones.get(prop.args[1], prop.args[1])
            elif prop.predicate == "crime_at":
                options = when.get(prop.args[0], {})
                mine = prop.args[1]
            else:
                options = {prop.key: solid[prop.key]} if prop.key in solid else {}
                mine = prop.key
            for_it = options.get(mine, 0)
            against_it = sum(weight for option, weight in options.items() if option != mine)
            status = beliefs[prop.key].status if prop.key in beliefs else "withdrawn"
            if against_it >= BELIEVE_AT and for_it == 0 and status == "rejected":
                refuted.setdefault(item.voice, set()).add(prop.key)
            elif for_it >= BELIEVE_AT and against_it == 0 and status == "believed":
                corroborated.setdefault(item.voice, set()).add(prop.key)
    return {
        voice: Credibility(
            standing="impeached" if voice in refuted else "corroborated",
            refuted=tuple(sorted(refuted.get(voice, ()))),
            corroborated=tuple(sorted(corroborated.get(voice, ()))),
        )
        for voice in sorted(set(refuted) | set(corroborated))
    }


def _status(support: int, contra: int) -> str:
    if support == 0:
        return "rejected" if contra >= BELIEVE_AT else "withdrawn"
    net = support - contra
    if net >= BELIEVE_AT:
        return "believed"
    if net <= -BELIEVE_AT:
        return "rejected"
    return "disputed" if contra > 0 else "tentative"


def contradiction_key(a: str, b: str) -> str:
    first, second = sorted((a, b))
    return f"{first}|{second}"


def revise(items: Iterable[Item], ctx: ReasoningContext) -> Revision:
    """Two passes, no iteration: weigh everything at face value, see whose word that
    refutes, then weigh again with those speakers' other claims discounted."""
    ordered = sorted(items, key=lambda item: item.id)
    revision = _revise(ordered, ctx, None)
    credibility = assess_speakers(ordered, ctx, revision.beliefs)
    refuted = {voice: frozenset(c.refuted) for voice, c in credibility.items() if c.standing == "impeached"}
    if refuted:
        revision = _revise(ordered, ctx, refuted)
    revision.credibility = credibility
    return revision


def _revise(ordered: list[Item], ctx: ReasoningContext, refuted: Refuted | None) -> Revision:
    # 1. Direct support.
    base: dict[str, _Agg] = {}
    for item in ordered:
        for prop in item.asserts:
            agg = base.setdefault(prop.key, _Agg(prop))
            weight = _weight(item, prop, ctx, refuted)
            if item.kind == "hearsay":
                agg.hearsay = max(agg.hearsay, weight)
            elif item.kind == "testimony":
                # One voice counts once: said twice, or said once and passed on by
                # others, it is still one person's word.
                agg.by_speaker[item.voice] = max(agg.by_speaker.get(item.voice, 0), weight)
            else:
                agg.solid += weight
            if item.id not in agg.ids:
                agg.ids.append(item.id)

    props: dict[str, Proposition] = {key: agg.prop for key, agg in base.items()}
    derivations: dict[str, list[Derivation]] = {}

    def direct(key: str) -> int:
        return base[key].total if key in base else 0

    def derive(prop: Proposition, rule: str, premises: list[str], active: bool = True, defeated_by: str | None = None) -> None:
        props.setdefault(prop.key, prop)
        derivations.setdefault(prop.key, []).append(
            Derivation(rule=rule, premises=tuple(premises), active=active, defeated_by=defeated_by)
        )

    def derived(key: str) -> int:
        return DERIVED_WEIGHT if any(d.active for d in derivations.get(key, [])) else 0

    def by_predicate(predicate: str) -> list[Proposition]:
        return sorted((p for p in props.values() if p.predicate == predicate), key=lambda p: p.key)

    def zone_of(location: str) -> str:
        return ctx.zones.get(location, location)

    # 2. R2: a credential written to a blank card means a duplicate exists.
    for written in by_predicate("card_written"):
        if direct(written.key) >= BELIEVE_AT:
            derive(Proposition(predicate="card_cloned", args=(written.args[0],)), "R2", [written.key])

    def cloned(card: str) -> bool:
        key = f"card_cloned({card})"
        return direct(key) + derived(key) >= BELIEVE_AT

    # 3. R3: whoever was where the duplicate was made could use it.
    #    Uses direct presence evidence only, so the rules cannot feed themselves.
    in_zone: dict[tuple[str, str, str], list[str]] = {}  # (person, slot, zone) -> the `at` statements saying so
    for at in by_predicate("at"):
        person, location, slot = at.args
        in_zone.setdefault((person, slot, zone_of(location)), []).append(at.key)
    direct_presence: dict[tuple[str, str], dict[str, int]] = {}
    for (person, slot, zone), keys in in_zone.items():
        direct_presence.setdefault((person, slot), {})[zone] = _together(base[k] for k in keys if k in base)

    for written in by_predicate("card_written"):
        if direct(written.key) < BELIEVE_AT:
            continue
        card, location, slot = written.args
        zone = zone_of(location)
        for (person, at_slot), weights in sorted(direct_presence.items()):
            if at_slot != slot:
                continue
            here = weights.get(zone, 0)
            elsewhere = sum(w for z, w in weights.items() if z != zone)
            if here - elsewhere >= BELIEVE_AT:
                premises = [written.key] + [
                    p.key for p in by_predicate("at")
                    if p.args[0] == person and p.args[2] == slot and zone_of(p.args[1]) == zone and direct(p.key) > 0
                ]
                derive(Proposition(predicate="could_use", args=(person, card)), "R3", premises)

    def could_use(person: str, card: str) -> bool:
        key = f"could_use({person},{card})"
        return direct(key) + derived(key) >= BELIEVE_AT

    # 4. R1 / R4: a card use places someone at the reader.
    for used in by_predicate("card_used"):
        if direct(used.key) < BELIEVE_AT:
            continue
        card, location, slot = used.args
        holders = [h.args[1] for h in by_predicate("card_holder") if h.args[0] == card and direct(h.key) >= BELIEVE_AT]
        is_cloned = cloned(card)
        clone_key = f"card_cloned({card})"
        for holder in holders:
            derive(
                Proposition(predicate="at", args=(holder, location, slot)),
                "R1",
                [used.key, f"card_holder({card},{holder})"],
                active=not is_cloned,
                defeated_by=clone_key if is_cloned else None,
            )
        if is_cloned:
            for candidate in by_predicate("could_use"):
                person, candidate_card = candidate.args
                if candidate_card == card and person not in holders and could_use(person, card):
                    derive(
                        Proposition(predicate="at", args=(person, location, slot)),
                        "R4",
                        [used.key, clone_key, candidate.key],
                    )

    # 5. Presence is judged per person and slot at zone granularity.
    presence: dict[tuple[str, str], dict[str, int]] = {}
    zone_ids: dict[tuple[str, str, str], list[str]] = {}
    own_support: dict[str, int] = {}
    for at in by_predicate("at"):
        person, location, slot = at.args
        own = direct(at.key) + derived(at.key)
        own_support[at.key] = own
        zone = zone_of(location)
        weights = presence.setdefault((person, slot), {})
        # Direct support is counted once per zone (one voice, one vote); what the
        # rules derive is added per statement, as each derivation has its own premises.
        weights[zone] = weights.get(zone, direct_presence.get((person, slot), {}).get(zone, 0)) + derived(at.key)
        ids = zone_ids.setdefault((person, slot, zone), [])
        for item_id in base[at.key].ids if at.key in base else []:
            if item_id not in ids:
                ids.append(item_id)

    beliefs: dict[str, BeliefEntry] = {}
    contradictions: set[str] = set()

    for at in by_predicate("at"):
        person, location, slot = at.args
        zone = zone_of(location)
        weights = presence[(person, slot)]
        own = own_support[at.key]
        support = weights[zone] if own > 0 else 0
        contra = sum(w for z, w in weights.items() if z != zone)
        against: list[str] = []
        for other_zone in sorted(weights):
            if other_zone != zone:
                against.extend(zone_ids.get((person, slot, other_zone), []))
        beliefs[at.key] = BeliefEntry(
            support=support,
            contra=contra,
            status=_status(support, contra),
            evidence=tuple(zone_ids.get((person, slot, zone), [])) if own > 0 else (),
            against=tuple(against),
            derivations=tuple(derivations.get(at.key, [])),
        )
        if own > 0:
            for other in by_predicate("at"):
                same_subject = other.args[0] == person and other.args[2] == slot
                if same_subject and zone_of(other.args[1]) != zone and own_support[other.key] > 0:
                    contradictions.add(contradiction_key(at.key, other.key))

    # 6. Everything that has no natural opposite.
    for key in sorted(props):
        prop = props[key]
        if prop.predicate in ("at", "took", "crime_at"):
            continue
        support = direct(key) + derived(key)
        beliefs[key] = BeliefEntry(
            support=support,
            contra=0,
            status=_status(support, 0),
            evidence=tuple(base[key].ids) if key in base else (),
            derivations=tuple(derivations.get(key, [])),
        )

    # 7. When: the object was taken once, so different times for the crime at the same
    #    place weigh against each other, exactly as two places do for one person. The
    #    crime slot is the one that is believed at the known crime location, if any.
    crime_weights: dict[str, dict[str, int]] = {}
    for crime in by_predicate("crime_at"):
        location, slot = crime.args
        crime_weights.setdefault(location, {})[slot] = direct(crime.key)
    crime_slot: str | None = None
    for crime in by_predicate("crime_at"):
        location, slot = crime.args
        weights = crime_weights[location]
        support = weights[slot]
        rivals = [f"crime_at({location},{other})" for other in sorted(weights) if other != slot and weights[other] > 0]
        contra = sum(weights[other] for other in weights if other != slot)
        beliefs[crime.key] = BeliefEntry(
            support=support,
            contra=contra,
            status=_status(support, contra),
            evidence=tuple(base[crime.key].ids),
            against=tuple(item_id for rival in rivals for item_id in base[rival].ids),
        )
        if support > 0:
            contradictions.update(contradiction_key(crime.key, rival) for rival in rivals)
        if location == ctx.crime_location and beliefs[crime.key].status == "believed":
            crime_slot = slot
    crime_zone = zone_of(ctx.crime_location)

    # 8. Per-suspect assessment: opportunity, means, motive, allegations.
    assessments: dict[str, SuspectAssessment] = {}
    for suspect in ctx.suspects:
        refs: list[str] = []

        opportunity = "none"
        if crime_slot is not None and (suspect, crime_slot) in presence:
            weights = presence[(suspect, crime_slot)]
            here = weights.get(crime_zone, 0)
            elsewhere = sum(w for z, w in weights.items() if z != crime_zone)
            net = here - elsewhere
            if net >= BELIEVE_AT:
                opportunity = "strong"
            elif net <= -BELIEVE_AT:
                opportunity = "alibi"
            elif here > 0 and elsewhere > 0:
                opportunity = "contested"
            elif here > 0:
                opportunity = "weak"
            if here > 0:
                refs.extend(zone_ids.get((suspect, crime_slot, crime_zone), []))
                refs.extend(base[k].ids[0] for k in (f"crime_at({ctx.crime_location},{crime_slot})",) if k in base)

        means = False
        for used in by_predicate("card_used"):
            card, location, _slot = used.args
            if location != ctx.crime_location or direct(used.key) < BELIEVE_AT:
                continue
            if cloned(card):
                qualifies = could_use(suspect, card)
                chain = [used.key, f"card_cloned({card})", f"could_use({suspect},{card})"]
            else:
                qualifies = direct(f"card_holder({card},{suspect})") >= BELIEVE_AT
                chain = [used.key, f"card_holder({card},{suspect})"]
            if qualifies:
                means = True
                refs.extend(_ids_behind(chain, base, derivations))
        # R5: the crime needed a tool, and the suspect had it when the crime happened.
        if crime_slot is not None:
            for used in by_predicate("crime_used"):
                custody = f"had({suspect},{used.args[0]},{crime_slot})"
                if direct(used.key) >= BELIEVE_AT and direct(custody) >= BELIEVE_AT:
                    means = True
                    refs.extend(_ids_behind([used.key, custody], base, derivations))

        motive_key = f"has_motive({suspect})"
        motive_weight = direct(motive_key)
        motive = "strong" if motive_weight >= BELIEVE_AT else "weak" if motive_weight > 0 else "none"
        if motive_weight > 0:
            refs.extend(base[motive_key].ids)

        named_key = f"took({suspect},{ctx.crime_object})"
        named = min(direct(named_key), NAMED_CAP)

        score = OPPORTUNITY_POINTS[opportunity] + (MEANS_POINTS if means else 0) + MOTIVE_POINTS[motive] + named
        assessments[suspect] = SuspectAssessment(
            score=score,
            opportunity=opportunity,
            means=means,
            motive=motive,
            named=named,
            evidence=tuple(dict.fromkeys(refs)),
        )

    ranked = sorted(ctx.suspects, key=lambda s: (-assessments[s].score, s))
    prime: str | None = None
    if ranked:
        top = assessments[ranked[0]].score
        tied = len(ranked) > 1 and assessments[ranked[1]].score == top
        if top >= PRIME_MINIMUM and not tied:
            prime = ranked[0]

    # 9. Guilt is never believed because someone said so: its status follows the assessment.
    for suspect in ctx.suspects:
        a = assessments[suspect]
        key = f"took({suspect},{ctx.crime_object})"
        positive = max(OPPORTUNITY_POINTS[a.opportunity], 0) + (MEANS_POINTS if a.means else 0) + MOTIVE_POINTS[a.motive] + a.named
        negative = 4 if a.opportunity == "alibi" else 0
        if positive == 0 and negative == 0 and key not in base:
            continue
        if meets_standard(assessments, suspect):
            status = "believed"
        elif a.opportunity == "alibi":
            status = "rejected"
        elif a.opportunity == "contested":
            status = "disputed"
        elif positive > 0:
            status = "tentative"
        else:
            status = "withdrawn"
        beliefs[key] = BeliefEntry(
            support=positive,
            contra=negative,
            status=status,
            evidence=tuple(dict.fromkeys(list(a.evidence) + (base[key].ids if key in base else []))),
        )

    return Revision(
        beliefs=dict(sorted(beliefs.items())),
        suspects=assessments,
        prime_suspect=prime,
        contradictions=sorted(contradictions),
    )


def _ids_behind(keys: list[str], base: dict[str, _Agg], derivations: dict[str, list[Derivation]], depth: int = 0) -> list[str]:
    """Evidence ids behind a set of propositions, following active derivations."""
    ids: list[str] = []
    for key in keys:
        if key in base:
            ids.extend(base[key].ids)
        if depth < 3:
            for derivation in derivations.get(key, []):
                if derivation.active:
                    ids.extend(_ids_behind(list(derivation.premises), base, derivations, depth + 1))
    return ids


def meets_standard(assessments: Mapping[str, SuspectAssessment], suspect: str) -> bool:
    """The standard of proof: opportunity, means and motive, and a clear lead.

    Each leg must be believed in its own right, and direct allegations
    (`named`) affect ranking but can never satisfy the standard.

    The function judges whatever assessments it is given, so the result is
    relative to the weights behind them. There are two uses:

    - *Personal conviction.* An agent's own assessments use its disposition.
      With the default hearsay weight of 1, a motive known only through
      hearsay is "weak" and fails. An agent that weighs hearsay at 2 (the
      journalist) reaches "strong" on hearsay alone and can be personally
      convinced by it.
    - *The reference standard.* Evaluation and the scenario lint always
      recompute assessments with hearsay weight 1 (`reasoning_context(1)`),
      so a motive resting on hearsay alone never counts as proof there,
      whoever held it.
    """
    candidate = assessments.get(suspect)
    if candidate is None:
        return False
    if candidate.opportunity != "strong" or not candidate.means or candidate.motive != "strong":
        return False
    return all(
        candidate.score - other.score >= PROOF_MARGIN
        for name, other in assessments.items()
        if name != suspect
    )
