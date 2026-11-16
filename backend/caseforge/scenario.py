"""Scenario loading and lint.

A scenario is data. The lint checks mechanically what an author would otherwise
have to promise: the truth is consistent, hard records do not lie, every record
can be acquired, and the records an accuser can come to hold are sufficient for
the reference reasoner to reach the culprit.

Acquisition is modelled twice (`reach`):

- *cooperative*: every agent answers every request in full and nobody is
  overruled. This is what an honest team can reach.
- *compelled*: the same, plus what an agent with `can_compel` gains by taking
  over an operator's sources. The engine allows that once the operator refused
  a search or was caught leaving a record out, and any operator may refuse, so
  the model grants it wherever the compelling agent could have sent that
  operator a search request at all.

The compelled closure is the upper bound on legal play without interventions,
and the lint rejects only what lies outside it. It is not a plan: it ignores
the tick limit and assumes whichever behaviour of the others helps most.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Iterable

from .canon import canonical_json, sha256_hex
from .models import (
    PREDICATES,
    AgentSpec,
    Entity,
    EvidenceSpec,
    InterventionSpec,
    Proposition,
    ScenarioPrivate,
    ScenarioPublic,
    SourceSpec,
)
from .reasoning import Item, ReasoningContext, meets_standard, revise

ANONYMOUS = "anonymous"
RESERVED_ID = re.compile(r"[CORS]\d+")  # ids the engine gives to claims, observations, requests and statements


class Scenario:
    """A validated scenario with lookup indexes. Immutable by convention."""

    def __init__(self, public: ScenarioPublic, private: ScenarioPrivate) -> None:
        self.public = public
        self.private = private
        self.entities: dict[str, Entity] = {e.id: e for e in (*public.entities, *private.hidden_entities)}
        self.public_entity_ids: frozenset[str] = frozenset(e.id for e in public.entities)
        self.evidence: dict[str, EvidenceSpec] = {e.id: e for e in private.evidence}
        self.sources: dict[str, SourceSpec] = {s.id: s for s in public.sources}
        self.agents: dict[str, AgentSpec] = {a.id: a for a in public.agents}
        self.agent_ids: tuple[str, ...] = tuple(a.id for a in public.agents)
        self.slots: dict[str, str] = {s.id: s.label for s in public.slots}
        self.interventions: dict[str, InterventionSpec] = {i.id: i for i in public.interventions}
        self.zones: dict[str, str] = {
            e.id: (e.zone or e.id) for e in self.entities.values() if e.kind == "location"
        }
        self.content_hash: str = sha256_hex(
            canonical_json({"public": public.model_dump(mode="json"), "private": private.model_dump(mode="json")})
        )

    @property
    def id(self) -> str:
        return self.public.id

    @property
    def version(self) -> str:
        return self.public.version

    @property
    def case(self):
        return self.public.case

    @property
    def truth(self):
        return self.private.truth

    def reasoning_context(self, hearsay_weight: int = 1) -> ReasoningContext:
        return ReasoningContext(
            zones=self.zones,
            suspects=self.case.suspects,
            crime_location=self.case.crime_location,
            crime_object=self.case.object,
            hearsay_weight=hearsay_weight,
        )

    def item_for(self, evidence_id: str) -> Item:
        spec = self.evidence[evidence_id]
        return Item(id=spec.id, kind=spec.kind, speaker=spec.speaker, asserts=spec.asserts)

    def truth_value(self, prop: Proposition) -> bool | None:
        """True, False, or None when the truth block does not settle the matter."""
        facts = {fact.key: fact for fact in self.truth.facts}
        if prop.key in facts:
            return True
        if prop.predicate == "at":
            person, location, slot = prop.args
            true_zones = {
                self.zones.get(f.args[1], f.args[1])
                for f in self.truth.facts
                if f.predicate == "at" and f.args[0] == person and f.args[2] == slot
            }
            if not true_zones:
                return None
            return None if self.zones.get(location, location) in true_zones else False
        if prop.predicate == "took":
            return prop.args[0] == self.truth.culprit and prop.args[1] == self.case.object
        # Every other predicate is closed-world: what the truth block omits is false.
        return False


def load_scenario_file(path: str | Path) -> Scenario:
    return load_scenario_data(json.loads(Path(path).read_text(encoding="utf-8")))


def load_scenario_data(data: dict) -> Scenario:
    scenario = Scenario(
        ScenarioPublic.model_validate(data["public"]),
        ScenarioPrivate.model_validate(data["private"]),
    )
    problems = lint(scenario)
    if problems:
        raise ValueError("scenario failed validation:\n- " + "\n- ".join(problems))
    return scenario


def bundled_scenario_ids() -> list[str]:
    folder = resources.files("caseforge").joinpath("scenarios")
    return sorted(entry.name[:-5] for entry in folder.iterdir() if entry.name.endswith(".json"))


_CACHE: dict[str, Scenario] = {}


def load_bundled(scenario_id: str) -> Scenario:
    if scenario_id not in _CACHE:
        if scenario_id not in bundled_scenario_ids():
            raise KeyError(f"unknown scenario: {scenario_id}")
        text = resources.files("caseforge").joinpath("scenarios", f"{scenario_id}.json").read_text(encoding="utf-8")
        _CACHE[scenario_id] = load_scenario_data(json.loads(text))
    return _CACHE[scenario_id]


def _check_proposition(scenario: Scenario, prop: Proposition, where: str) -> list[str]:
    problems = []
    for arg, kind in zip(prop.args, PREDICATES[prop.predicate]):
        if kind == "slot":
            if arg not in scenario.slots:
                problems.append(f"{where}: unknown time slot {arg!r} in {prop.key}")
        else:
            entity = scenario.entities.get(arg)
            if entity is None:
                problems.append(f"{where}: unknown entity {arg!r} in {prop.key}")
            elif entity.kind != kind:
                problems.append(f"{where}: {arg!r} is a {entity.kind}, but {prop.predicate} expects a {kind}")
    return problems


def lint(scenario: Scenario) -> list[str]:
    """Return every structural or logical problem found. Empty means valid."""
    problems: list[str] = []
    case, truth = scenario.case, scenario.truth

    def require_ids(ids: Iterable[str], known: Iterable[str], where: str) -> None:
        known_set = set(known)
        for value in ids:
            if value not in known_set:
                problems.append(f"{where}: unknown id {value!r}")

    # References.
    for agent in scenario.public.agents:
        entity = scenario.entities.get(agent.id)
        if entity is None or entity.kind != "person" or agent.id not in scenario.public_entity_ids:
            problems.append(f"agent {agent.id}: must be a public person entity")
        require_ids(agent.disposition.shares_with, scenario.agents, f"agent {agent.id} shares_with")
        require_ids((k for k in agent.disposition.disclosure if k != "*"), scenario.agents, f"agent {agent.id} disclosure")
    require_ids(case.suspects, scenario.public_entity_ids, "case.suspects")
    require_ids([case.object, case.crime_location], scenario.public_entity_ids, "case")
    if not any(a.disposition.can_accuse for a in scenario.public.agents):
        problems.append("no agent can accuse: the case could never be closed by a conclusion")
    for source in scenario.public.sources:
        require_ids(source.operators, scenario.agents, f"source {source.id} operators")
        require_ids(source.requesters, scenario.agents, f"source {source.id} requesters")
        require_ids(source.searchable, scenario.entities, f"source {source.id} searchable")
        if not source.operators:
            problems.append(f"source {source.id}: has no operator")
    for evidence in scenario.private.evidence:
        where = f"evidence {evidence.id}"
        if RESERVED_ID.fullmatch(evidence.id):
            problems.append(f"{where}: ids of the form C1, O1, R1, S1 are taken by claims, observations, requests and statements")
        require_ids([evidence.source], scenario.sources, f"{where} source")
        require_ids(evidence.mentions, scenario.entities, f"{where} mentions")
        require_ids(evidence.requires, scenario.evidence, f"{where} requires")
        for prop in evidence.asserts:
            problems.extend(_check_proposition(scenario, prop, where))
            if prop.predicate == "could_use":
                problems.append(f"{where}: could_use is derived only and may not be asserted")
        if evidence.kind in ("testimony", "hearsay") and not evidence.speaker:
            problems.append(f"{where}: {evidence.kind} needs a speaker")
        source = scenario.sources.get(evidence.source)
        if source and not set(evidence.mentions) & set(source.searchable):
            problems.append(f"{where}: unreachable, its source cannot be queried about anything it mentions")
    for agent_id, held in scenario.private.initial_holdings.items():
        require_ids([agent_id], scenario.agents, "initial_holdings")
        require_ids(held, scenario.evidence, f"initial_holdings[{agent_id}]")
    for agent_id, seen in scenario.private.observations.items():
        require_ids([agent_id], scenario.agents, "observations")
        for prop in seen:
            problems.extend(_check_proposition(scenario, prop, f"observation of {agent_id}"))
    for agent_id, agenda in scenario.private.agendas.items():
        where = f"agenda of {agent_id}"
        require_ids([agent_id], scenario.agents, "agendas")
        for person in (agenda.protects, agenda.deflects_to):
            if person is not None and (person not in scenario.entities or scenario.entities[person].kind != "person"):
                problems.append(f"{where}: {person!r} is not a person")
        if agenda.leaks_to is not None and (agenda.leaks_to not in scenario.agents or agenda.leaks_to == agent_id):
            problems.append(f"{where}: leaks_to must be another agent")
        if agenda.deflects_to == agenda.protects:
            problems.append(f"{where}: cannot deflect suspicion onto the person it protects")
    for intervention in scenario.public.interventions:
        where = f"intervention {intervention.id}"
        require_ids(intervention.recipients, scenario.agents, f"{where} recipients")
        if intervention.kind == "release_evidence":
            if intervention.evidence not in scenario.evidence or not intervention.recipients:
                problems.append(f"{where}: needs a known evidence id and recipients")
        elif intervention.kind == "spread_rumor":
            if intervention.proposition is None or not intervention.recipients:
                problems.append(f"{where}: needs a proposition and recipients")
            else:
                problems.extend(_check_proposition(scenario, intervention.proposition, where))
        elif intervention.kind == "grant_access":
            if intervention.agent not in scenario.agents or intervention.source not in scenario.sources:
                problems.append(f"{where}: needs a known agent and source")
    if problems:
        return problems  # logical checks below assume references resolve

    # Truth is self-consistent.
    for fact in truth.facts:
        problems.extend(_check_proposition(scenario, fact, "truth"))
    if truth.culprit not in case.suspects:
        problems.append("truth.culprit is not among the suspects")
    if f"took({truth.culprit},{case.object})" not in {f.key for f in truth.facts}:
        problems.append("truth.facts must state that the culprit took the object")
    where_was: dict[tuple[str, str], set[str]] = {}
    for fact in truth.facts:
        if fact.predicate == "at":
            where_was.setdefault((fact.args[0], fact.args[2]), set()).add(scenario.zones[fact.args[1]])
    for (person, slot), zones in sorted(where_was.items()):
        if len(zones) > 1:
            problems.append(f"truth: {person} is in two zones at {slot}: {sorted(zones)}")
    require_ids(truth.key_evidence, scenario.evidence, "truth.key_evidence")
    for fact in truth.key_facts:
        if scenario.truth_value(fact) is not True:
            problems.append(f"truth.key_facts: {fact.key} is not true")

    # Hard records do not lie; only people do.
    for evidence in scenario.private.evidence:
        for prop in evidence.asserts:
            value = scenario.truth_value(prop)
            if evidence.kind in ("record", "forensic") and value is not True:
                problems.append(f"evidence {evidence.id}: a {evidence.kind} asserts {prop.key}, which is not true")
    # Nor do an agent's own eyes. What it goes on to say about it is another matter.
    for agent_id, seen in sorted(scenario.private.observations.items()):
        for prop in seen:
            if scenario.truth_value(prop) is not True:
                problems.append(f"observation of {agent_id}: {prop.key} is not true, and an agent cannot have seen what did not happen")

    # Reachability: every record can be acquired by the team without outside help.
    # Judged on the compelled closure: rejecting a record that an escalation can
    # reach would call a playable scenario impossible.
    found = reach(scenario)
    obtainable = found.obtainable(compelled=True)
    released = {i.evidence for i in scenario.public.interventions if i.kind == "release_evidence"}
    for evidence in scenario.private.evidence:
        if evidence.id in obtainable:
            continue
        if evidence.id in truth.key_evidence:
            problems.append(f"evidence {evidence.id}: key evidence can never be acquired ({_why_unreachable(scenario, evidence, obtainable)})")
        elif evidence.id not in released:
            # A record that only an intervention can deliver is allowed, but never a key one.
            problems.append(f"evidence {evidence.id}: can never be acquired ({_why_unreachable(scenario, evidence, obtainable)})")

    # Solvability: everything an accuser can come to hold must meet the reference
    # standard for the culprit. Interventions are not counted: a case must be solvable
    # without the operator's help. This is an authoring rule as much as a reachability
    # one: the complete picture has to point at the culprit, not just a lucky part of it.
    verdicts = []
    for accuser in accusers(scenario):
        if identifies_culprit(scenario, found.compelled[accuser]):
            verdicts = []
            break
        held = revise([scenario.item_for(e) for e in sorted(found.compelled[accuser])], scenario.reasoning_context())
        verdicts.append(f"unsolvable: the records {accuser} can acquire point at {held.prime_suspect!r} and do not meet the standard of proof for the culprit")
    problems.extend(verdicts)

    return problems


def accusers(scenario: Scenario) -> list[str]:
    return [a.id for a in scenario.public.agents if a.disposition.can_accuse]


def identifies_culprit(scenario: Scenario, evidence_ids: Iterable[str]) -> bool:
    """Does the reference reasoner, given exactly these records, meet the standard for the culprit?"""
    held = revise([scenario.item_for(e) for e in sorted(evidence_ids)], scenario.reasoning_context())
    culprit = scenario.truth.culprit
    return held.prime_suspect == culprit and meets_standard(held.suspects, culprit)


@dataclass(frozen=True)
class Reach:
    """What each agent can come to hold, with and without overruling an operator."""

    cooperative: dict[str, frozenset[str]]
    compelled: dict[str, frozenset[str]]
    takeovers: dict[str, tuple[str, ...]]  # compelling agent -> operators whose sources it could take over
    grounds: dict[str, dict[str, str]] = field(default_factory=dict)  # agent -> operator -> "request" | "conversation"

    def obtainable(self, compelled: bool) -> set[str]:
        sets = self.compelled if compelled else self.cooperative
        return set().union(*sets.values()) if sets else set()

    def route(self, agent_id: str, evidence_id: str) -> str:
        """How `agent_id` can come to hold a record: cooperative, escalation, or never."""
        if evidence_id in self.cooperative[agent_id]:
            return "cooperative"
        return "escalation" if evidence_id in self.compelled[agent_id] else "never"


def reach(scenario: Scenario) -> Reach:
    grounds: dict[str, dict[str, str]] = {}
    cooperative = acquirable(scenario, escalation=False)
    compelled = acquirable(scenario, escalation=True, _takeovers=grounds)
    return Reach(
        cooperative={a: frozenset(ids) for a, ids in cooperative.items()},
        compelled={a: frozenset(ids) for a, ids in compelled.items()},
        takeovers={a: tuple(sorted(ops)) for a, ops in grounds.items()},
        grounds=grounds,
    )


def reach_report(scenario: Scenario) -> dict:
    """What each accuser can hold by which route, and what solving the case depends on.

    `solvable` is "cooperative" when an honest team can put the case together,
    "escalation" when the accuser must first take over somebody's sources (which
    an operator who simply cooperates never gives grounds for), and "no".
    """
    found = reach(scenario)
    report: dict = {
        "accusers": {},
        "takeovers": {a: list(ops) for a, ops in sorted(found.takeovers.items())},
        "grounds": {a: dict(sorted(ops.items())) for a, ops in sorted(found.grounds.items())},
    }
    for accuser in accusers(scenario):
        routes = {e: found.route(accuser, e) for e in sorted(scenario.evidence)}
        if identifies_culprit(scenario, found.cooperative[accuser]):
            solvable = "cooperative"
        elif identifies_culprit(scenario, found.compelled[accuser]):
            solvable = "escalation"
        else:
            solvable = "no"
        report["accusers"][accuser] = {
            "solvable": solvable,
            "cooperative": [e for e, r in routes.items() if r == "cooperative"],
            "escalation": [e for e, r in routes.items() if r == "escalation"],
            "never": [e for e, r in routes.items() if r == "never"],
        }
    return report


def acquirable(scenario: Scenario, escalation: bool = True, _takeovers: dict | None = None) -> dict[str, set[str]]:
    """For each agent, the records it could come to hold.

    A fixpoint over the rules the engine enforces (`actions.validate_action`,
    `actions.query_source`, `views.source_mode`, `views.known_entity_ids`):

    - a query needs a topic the asker knows of, filed under that source;
    - a direct search needs the record's prerequisites in the searcher's own
      hands; a requested one may draw on the requester's and the operator's;
    - the operator sees whatever it retrieves; the requester receives it only
      if the record may be passed on;
    - shareable records travel freely between agents;
    - an agent who can publish can make any person or object it knows of known
      to everybody, because a claim names its subject.

    With `escalation`, an agent with `can_compel` also gets direct access to
    every source of an operator who could give it grounds, because grounds open
    all of that operator's sources (`actions.escalation_grounds`,
    `escalation_targets`). The engine accepts two kinds, and so does this:

    - *a search request.* The agent may ask that operator to search a source
      (it is a requester of a source the operator runs and knows a topic the
      source is filed under). The operator may refuse, or leave a record out.
    - *a conversation.* Anybody may ask anybody what they know about a topic
      (`Request` without a source needs no authority). The operator may answer
      and leave out a record it holds. That shows as soon as the asker holds
      the same record, so it needs a record that may be passed on, held by
      both, naming something the asker knows of.

    Without `escalation`, the result is what a fully cooperative team reaches.

    Interventions are not applied. With `escalation` this is an upper bound on
    what play can reach without them: it assumes every operator who could
    misbehave in a way that gives grounds does so. It says what is not
    impossible. It never says a policy will get there.
    """
    agents = scenario.agent_ids
    held: dict[str, set[str]] = {a: set(scenario.private.initial_holdings.get(a, ())) for a in agents}
    taken: dict[str, set[str]] = {a: set() for a in agents}  # sources opened by an escalation
    overruled: dict[str, dict[str, str]] = {a: {} for a in agents}  # operator -> kind of grounds
    publishers = [a for a in agents if scenario.agents[a].disposition.can_publish]
    compellers = [a for a in agents if scenario.agents[a].disposition.can_compel] if escalation else []
    nameable = {e.id for e in scenario.entities.values() if e.kind in ("person", "object")}

    def known_without_claims(agent_id: str) -> set[str]:
        ids = set(scenario.public_entity_ids)
        for evidence_id in held[agent_id]:
            ids.update(scenario.evidence[evidence_id].mentions)
        return ids

    def known(agent_id: str) -> set[str]:
        ids = known_without_claims(agent_id)
        for publisher in publishers:
            if publisher != agent_id:
                ids |= known_without_claims(publisher) & nameable
        return ids

    def direct(agent_id: str, source: SourceSpec) -> bool:
        return source.id in taken[agent_id] or (agent_id in source.operators and source.self_serve)

    changed = True
    while changed:
        changed = False
        for agent_id in compellers:
            mine = known(agent_id)
            for operator in agents:
                if operator == agent_id or operator in overruled[agent_id]:
                    continue
                can_ask = any(
                    agent_id in s.requesters and operator in s.operators and set(s.searchable) & mine
                    for s in scenario.public.sources
                )
                # A record both hold: asked about something it names, the operator can
                # leave it out of the answer, and the asker can see that it did.
                can_catch = any(
                    scenario.evidence[e].shareable and e in held[agent_id] and set(scenario.evidence[e].mentions) & mine
                    for e in held[operator]
                )
                if can_ask or can_catch:
                    overruled[agent_id][operator] = "request" if can_ask else "conversation"
                    taken[agent_id] |= {s.id for s in scenario.public.sources if operator in s.operators}
                    changed = True
        for evidence in scenario.private.evidence:
            source = scenario.sources[evidence.source]
            topics = set(evidence.mentions) & set(source.searchable)
            needs = set(evidence.requires)
            for agent_id in agents:
                if not topics & known(agent_id):
                    continue
                if evidence.id not in held[agent_id] and direct(agent_id, source) and needs <= held[agent_id]:
                    held[agent_id].add(evidence.id)
                    changed = True
                if agent_id in source.requesters:
                    # Asking is open even to someone who already holds the record, and to
                    # every operator in turn: each operator asked sees what it retrieves.
                    for operator in source.operators:
                        if operator != agent_id and needs <= held[agent_id] | held[operator]:
                            gained = {operator} | ({agent_id} if evidence.shareable else set())
                            for holder in gained:
                                if evidence.id not in held[holder]:
                                    held[holder].add(evidence.id)
                                    changed = True
        shared = {e for ids in held.values() for e in ids if scenario.evidence[e].shareable}
        for agent_id in agents:
            if not shared <= held[agent_id]:
                held[agent_id] |= shared
                changed = True
    if _takeovers is not None:
        _takeovers.update({a: dict(sorted(ops.items())) for a, ops in overruled.items() if ops})
    return held


def _why_unreachable(scenario: Scenario, evidence: EvidenceSpec, obtainable: set[str]) -> str:
    source = scenario.sources[evidence.source]
    if not source.self_serve and not source.requesters:
        return f"source {source.id} needs a requester and has none"
    missing = sorted(set(evidence.requires) - obtainable)
    if evidence.id in evidence.requires:
        return "it requires itself"
    if missing:
        return f"its prerequisites can never be met: {', '.join(missing)}"
    return f"nobody who may query {source.id} can learn of a topic it is filed under, even after taking over an operator's sources"
