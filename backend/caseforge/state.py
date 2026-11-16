"""Simulation state and the reducer that derives it from events.

`apply_event` is the single place state changes. The live engine and replay
both go through it, so "replayed state equals live state" holds by
construction. The reducer needs no scenario: every fact it uses is in the
event payloads.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from pydantic import BaseModel, Field

from .canon import GENESIS_HASH
from .models import BeliefEntry, Credibility, Event, SuspectAssessment
from .reasoning import contradiction_key


class Holding(BaseModel):
    """An agent's copy of an evidence record and how it got there."""

    evidence: str
    seq: int
    tick: int
    via: str  # initial | inspect | shared | released
    from_agent: str | None = None
    chain: list[str] = Field(default_factory=list)  # custody: first holder ... this agent
    also: list[dict[str, Any]] = Field(default_factory=list)  # later deliveries of the same record


class Ref(BaseModel):
    """A pointer to the event that caused something."""

    seq: int
    tick: int


class Stamp(BaseModel):
    """The event that introduced a belief or relationship, and the one that last changed it."""

    first: Ref
    last: Ref


class Discrepancy(BaseModel):
    """An answer this agent caught leaving out a record it later came to hold."""

    against: str
    request: str
    evidence: str
    seq: int
    tick: int


class Tried(BaseModel):
    seq: int
    found: int
    count: int


class StandingChange(BaseModel):
    standing: str | None  # None: nothing checkable is left
    seq: int
    tick: int


class CredibilityState(BaseModel):
    """One listener's current view of one speaker, and every standing it went through."""

    current: Credibility | None = None
    history: list[StandingChange] = Field(default_factory=list)


class StanceChange(BaseModel):
    stance: str
    belief: str
    seq: int
    tick: int


class StatementState(BaseModel):
    id: str
    speaker: str
    recipient: str
    proposition: str
    origin: str | None = None
    relays: str | None = None
    grounds: str  # what the speaker had for it; never part of the recipient's view
    backing: list[str] = Field(default_factory=list)
    seq: int
    tick: int
    stances: list[StanceChange] = Field(default_factory=list)  # the recipient's, oldest first


class AgentState(BaseModel):
    id: str
    policy: str
    holdings: dict[str, Holding] = Field(default_factory=dict)
    heard: dict[str, int] = Field(default_factory=dict)  # claim id -> seq at which it was heard
    beliefs: dict[str, BeliefEntry] = Field(default_factory=dict)
    suspects: dict[str, SuspectAssessment] = Field(default_factory=dict)
    prime_suspect: str | None = None
    contradictions: list[str] = Field(default_factory=list)
    # Provenance of reasoning. Bookkeeping only: the reducer records which event
    # brought a belief in or changed it; it never computes a belief.
    belief_stamps: dict[str, Stamp] = Field(default_factory=dict)  # proposition key -> stamp
    derivation_stamps: dict[str, dict[str, Stamp]] = Field(default_factory=dict)  # conclusion -> "rule|premise" -> stamp
    contradiction_refs: dict[str, Ref] = Field(default_factory=dict)  # pair -> event that recognized it
    prime_since: Ref | None = None  # event that made the current prime suspect prime
    revised: Ref | None = None  # this agent's latest BeliefsRevised
    tried: dict[str, Tried] = Field(default_factory=dict)  # "source|topic" -> last own-initiative query
    shared: list[str] = Field(default_factory=list)  # "recipient|evidence"
    granted: list[str] = Field(default_factory=list)  # sources opened by intervention or escalation
    discrepancies: list[Discrepancy] = Field(default_factory=list)
    escalated: list[str] = Field(default_factory=list)  # operators this agent went over the head of
    credibility: dict[str, CredibilityState] = Field(default_factory=dict)  # speaker -> what this agent could check
    actions: int = 0
    rejected: int = 0


class ClaimState(BaseModel):
    id: str
    by: str
    proposition: str
    cited: list[str]
    audience: list[str]
    text: str | None = None
    seq: int
    tick: int
    status: str = "active"  # active | retracted
    retracted_seq: int | None = None
    retracted_tick: int | None = None


class RequestState(BaseModel):
    id: str
    sender: str
    recipient: str
    topic: str
    source: str | None = None
    seq: int
    tick: int
    status: str = "pending"  # pending | fulfilled | nothing_found | declined
    answered_seq: int | None = None
    answered_tick: int | None = None
    evidence: list[str] = Field(default_factory=list)
    withheld: list[str] = Field(default_factory=list)  # found but not handed over; never part of the requester's view


class Discovery(BaseModel):
    by: str
    seq: int
    tick: int
    via: str


class SimState(BaseModel):
    scenario_id: str = ""
    scenario_version: str = ""
    scenario_hash: str = ""
    engine_version: str = ""
    seed: int = 0
    max_ticks: int = 0
    tick: int = 0
    seq: int = -1
    head_hash: str = GENESIS_HASH
    status: str = "running"  # running | closed
    close_reason: str | None = None
    order: list[str] = Field(default_factory=list)
    agents: dict[str, AgentState] = Field(default_factory=dict)
    claims: dict[str, ClaimState] = Field(default_factory=dict)
    requests: dict[str, RequestState] = Field(default_factory=dict)
    statements: dict[str, StatementState] = Field(default_factory=dict)
    discovered: dict[str, Discovery] = Field(default_factory=dict)
    interventions: list[str] = Field(default_factory=list)
    accusation: dict[str, Any] | None = None


class ReplayError(Exception):
    pass


def _run_started(state: SimState, e: Event) -> None:
    d = e.data
    state.scenario_id = d["scenario_id"]
    state.scenario_version = d["scenario_version"]
    state.scenario_hash = d["scenario_hash"]
    state.engine_version = d["engine_version"]
    state.seed = d["seed"]
    state.max_ticks = d["max_ticks"]
    state.agents = {a: AgentState(id=a, policy=d["policies"][a]) for a in d["agents"]}


def _tick_started(state: SimState, e: Event) -> None:
    state.order = list(e.data["order"])


def _action_taken(state: SimState, e: Event) -> None:
    state.agents[e.data["agent"]].actions += 1


def _action_rejected(state: SimState, e: Event) -> None:
    state.agents[e.data["agent"]].rejected += 1


def _source_inspected(state: SimState, e: Event) -> None:
    d = e.data
    if d.get("on_behalf_of") is None:
        agent = state.agents[d["agent"]]
        key = f"{d['source']}|{d['topic']}"
        previous = agent.tried.get(key)
        agent.tried[key] = Tried(seq=e.seq, found=len(d["found"]), count=(previous.count if previous else 0) + 1)


def _deliver(state: SimState, e: Event, recipient: str, evidence: str, via: str, sender: str | None, chain: list[str]) -> None:
    agent = state.agents[recipient]
    if evidence in agent.holdings:
        agent.holdings[evidence].also.append({"seq": e.seq, "tick": e.tick, "via": via, "from_agent": sender})
    else:
        agent.holdings[evidence] = Holding(
            evidence=evidence, seq=e.seq, tick=e.tick, via=via, from_agent=sender, chain=chain
        )
    if evidence not in state.discovered:
        state.discovered[evidence] = Discovery(by=recipient, seq=e.seq, tick=e.tick, via=via)


def _evidence_observed(state: SimState, e: Event) -> None:
    d = e.data
    _deliver(state, e, d["agent"], d["evidence"], d["via"], None, [d["agent"]])


def _evidence_shared(state: SimState, e: Event) -> None:
    d = e.data
    sender = state.agents[d["sender"]]
    marker = f"{d['recipient']}|{d['evidence']}"
    if marker not in sender.shared:
        sender.shared.append(marker)
    origin = sender.holdings[d["evidence"]].chain if d["evidence"] in sender.holdings else [d["sender"]]
    _deliver(state, e, d["recipient"], d["evidence"], "shared", d["sender"], [*origin, d["recipient"]])


def _evidence_released(state: SimState, e: Event) -> None:
    d = e.data
    _deliver(state, e, d["recipient"], d["evidence"], "released", None, ["user", d["recipient"]])


def _request_sent(state: SimState, e: Event) -> None:
    d = e.data
    state.requests[d["request"]] = RequestState(
        id=d["request"], sender=d["sender"], recipient=d["recipient"], topic=d["topic"],
        source=d.get("source"), seq=e.seq, tick=e.tick,
    )


def _request_answered(state: SimState, e: Event) -> None:
    d = e.data
    request = state.requests[d["request"]]
    request.status = d["outcome"]
    request.answered_seq = e.seq
    request.answered_tick = e.tick
    request.evidence = list(d.get("evidence", []))


def _evidence_withheld(state: SimState, e: Event) -> None:
    state.requests[e.data["request"]].withheld = list(e.data["evidence"])


def _discrepancy_noticed(state: SimState, e: Event) -> None:
    d = e.data
    state.agents[d["agent"]].discrepancies.append(
        Discrepancy(against=d["against"], request=d["request"], evidence=d["evidence"], seq=e.seq, tick=e.tick)
    )


def _access_escalated(state: SimState, e: Event) -> None:
    agent = state.agents[e.data["agent"]]
    if e.data["source"] not in agent.granted:
        agent.granted.append(e.data["source"])
    if e.data["against"] not in agent.escalated:
        agent.escalated.append(e.data["against"])


def _claim_published(state: SimState, e: Event) -> None:
    d = e.data
    state.claims[d["claim"]] = ClaimState(
        id=d["claim"], by=d["by"], proposition=d["proposition"], cited=list(d.get("cited", [])),
        audience=list(d["audience"]), text=d.get("text"), seq=e.seq, tick=e.tick,
    )
    for listener in d["audience"]:
        state.agents[listener].heard[d["claim"]] = e.seq


def _claim_retracted(state: SimState, e: Event) -> None:
    claim = state.claims[e.data["claim"]]
    claim.status = "retracted"
    claim.retracted_seq = e.seq
    claim.retracted_tick = e.tick


def derivation_key(rule: str, premise: str) -> str:
    return f"{rule}|{premise}"


def _beliefs_revised(state: SimState, e: Event) -> None:
    d = e.data
    agent = state.agents[d["agent"]]
    ref = Ref(seq=e.seq, tick=e.tick)
    for key, entry in d["changes"].items():
        if entry is None:
            agent.beliefs.pop(key, None)
            agent.belief_stamps.pop(key, None)
            agent.derivation_stamps.pop(key, None)
            continue
        before = agent.beliefs.get(key)
        belief = BeliefEntry.model_validate(entry)
        agent.beliefs[key] = belief
        stamp = agent.belief_stamps.get(key)
        agent.belief_stamps[key] = Stamp(first=stamp.first if stamp else ref, last=ref)
        # A derivation keeps the event that introduced it; its "last" moves only when
        # it is defeated or restored.
        was_active = {derivation_key(x.rule, p): x.active for x in (before.derivations if before else ()) for p in x.premises}
        known = agent.derivation_stamps.get(key, {})
        current: dict[str, Stamp] = {}
        for derivation in belief.derivations:
            for premise in derivation.premises:
                dkey = derivation_key(derivation.rule, premise)
                previous = known.get(dkey)
                if previous is None:
                    current[dkey] = Stamp(first=ref, last=ref)
                elif was_active.get(dkey) != derivation.active:
                    current[dkey] = Stamp(first=previous.first, last=ref)
                else:
                    current[dkey] = previous
        if current:
            agent.derivation_stamps[key] = dict(sorted(current.items()))
        else:
            agent.derivation_stamps.pop(key, None)
    agent.beliefs = dict(sorted(agent.beliefs.items()))
    agent.belief_stamps = dict(sorted(agent.belief_stamps.items()))
    agent.derivation_stamps = dict(sorted(agent.derivation_stamps.items()))
    agent.suspects = {name: SuspectAssessment.model_validate(a) for name, a in d["suspects"].items()}
    if d["prime_after"] != agent.prime_suspect:
        agent.prime_since = ref if d["prime_after"] else None
    agent.prime_suspect = d["prime_after"]
    agent.revised = ref


def _contradiction_recognized(state: SimState, e: Event) -> None:
    d = e.data
    agent = state.agents[d["agent"]]
    key = contradiction_key(d["a"], d["b"])
    if key not in agent.contradictions:
        agent.contradictions.append(key)
        agent.contradiction_refs[key] = Ref(seq=e.seq, tick=e.tick)


def _statement_made(state: SimState, e: Event) -> None:
    d = e.data
    state.statements[d["statement"]] = StatementState(
        id=d["statement"], speaker=d["speaker"], recipient=d["recipient"], proposition=d["proposition"],
        origin=d.get("origin"), relays=d.get("relays"), grounds=d["grounds"], backing=list(d.get("backing", [])),
        seq=e.seq, tick=e.tick,
    )


def _statement_weighed(state: SimState, e: Event) -> None:
    d = e.data
    state.statements[d["statement"]].stances.append(
        StanceChange(stance=d["stance"], belief=d["belief"], seq=e.seq, tick=e.tick)
    )


def _credibility_revised(state: SimState, e: Event) -> None:
    d = e.data
    agent = state.agents[d["agent"]]
    entry = agent.credibility.setdefault(d["speaker"], CredibilityState())
    entry.current = Credibility.model_validate(d["credibility"]) if d["credibility"] is not None else None
    standing = entry.current.standing if entry.current else None
    if not entry.history or entry.history[-1].standing != standing:
        entry.history.append(StandingChange(standing=standing, seq=e.seq, tick=e.tick))
    agent.credibility = dict(sorted(agent.credibility.items()))


def _intervention_applied(state: SimState, e: Event) -> None:
    state.interventions.append(e.data["intervention"])


def _access_granted(state: SimState, e: Event) -> None:
    agent = state.agents[e.data["agent"]]
    if e.data["source"] not in agent.granted:
        agent.granted.append(e.data["source"])


def _policy_changed(state: SimState, e: Event) -> None:
    state.agents[e.data["agent"]].policy = e.data["policy"]


def _accusation_made(state: SimState, e: Event) -> None:
    d = e.data
    state.accusation = {"by": d["by"], "suspect": d["suspect"], "cited": list(d["cited"]), "seq": e.seq, "tick": e.tick}


def _case_closed(state: SimState, e: Event) -> None:
    state.status = "closed"
    state.close_reason = e.data["reason"]


_HANDLERS: dict[str, Callable[[SimState, Event], None]] = {
    "RunStarted": _run_started,
    "TickStarted": _tick_started,
    "ActionTaken": _action_taken,
    "ActionRejected": _action_rejected,
    "SourceInspected": _source_inspected,
    "EvidenceObserved": _evidence_observed,
    "EvidenceShared": _evidence_shared,
    "EvidenceReleased": _evidence_released,
    "RequestSent": _request_sent,
    "RequestAnswered": _request_answered,
    "EvidenceWithheld": _evidence_withheld,
    "DiscrepancyNoticed": _discrepancy_noticed,
    "AccessEscalated": _access_escalated,
    "ClaimPublished": _claim_published,
    "ClaimRetracted": _claim_retracted,
    "BeliefsRevised": _beliefs_revised,
    "ContradictionRecognized": _contradiction_recognized,
    "StatementMade": _statement_made,
    "StatementWeighed": _statement_weighed,
    "CredibilityRevised": _credibility_revised,
    "InterventionApplied": _intervention_applied,
    "AccessGranted": _access_granted,
    "PolicyChanged": _policy_changed,
    "AccusationMade": _accusation_made,
    "CaseClosed": _case_closed,
}


def apply_event(state: SimState, event: Event) -> None:
    """Advance state by exactly one event. Rejects gaps and reordering."""
    if event.seq != state.seq + 1:
        raise ReplayError(f"event {event.seq} applied out of order (state is at {state.seq})")
    handler = _HANDLERS.get(event.type)
    if handler is None:
        raise ReplayError(f"no reducer for event type {event.type}")
    handler(state, event)
    state.seq = event.seq
    state.tick = event.tick
    state.head_hash = event.hash


def fold(events: Iterable[Event]) -> SimState:
    state = SimState()
    for event in events:
        apply_event(state, event)
    return state


def state_fingerprint(state: SimState) -> dict[str, Any]:
    """Plain-data form of a state, suitable for equality checks in tests."""
    return state.model_dump(mode="json")
