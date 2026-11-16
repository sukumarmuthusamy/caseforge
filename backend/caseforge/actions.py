"""Action rules: preconditions, permissions and effects.

`validate_action` raises `ActionError` and touches nothing. `apply_action`
runs only after validation succeeded and expresses every effect as events.
Together they are the physics of the world: a policy can only ask.
"""

from __future__ import annotations

from typing import Any, Callable

from .models import (
    PREDICATES,
    PUBLISHABLE_PREDICATES,
    TELLABLE_PREDICATES,
    Accuse,
    Escalate,
    Event,
    Inspect,
    Proposition,
    Publish,
    Request,
    Respond,
    Retract,
    Share,
    Tell,
    Wait,
)
from .scenario import Scenario
from .state import SimState, StatementState
from .views import known_entity_ids, observations_of, source_mode

Emit = Callable[[str, str, dict[str, Any]], Event]
Dirty = dict[str, list[str]]  # agent id -> ids of the information that just reached it


class ActionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ActionError(code, message)


def query_source(scenario: Scenario, source_id: str, topic: str, basis: set[str]) -> list[str]:
    """Records a source yields for a topic, given what the querying side already holds."""
    return sorted(
        e.id
        for e in scenario.evidence.values()
        if e.source == source_id and topic in e.mentions and set(e.requires) <= basis
    )


def escalation_grounds(state: SimState, agent_id: str, against: str) -> list[str]:
    """Request ids that entitle `agent_id` to go over `against`'s head.

    Two things count: an answer the agent caught leaving a record out, and a
    refusal to run a search the agent was authorised to ask for.
    """
    grounds = {d.request for d in state.agents[agent_id].discrepancies if d.against == against}
    grounds |= {
        r.id for r in state.requests.values()
        if r.sender == agent_id and r.recipient == against and r.source is not None and r.status == "declined"
    }
    return sorted(grounds, key=lambda request_id: state.requests[request_id].seq)


def escalation_targets(scenario: Scenario, state: SimState, agent_id: str, against: str) -> list[str]:
    """Sources `against` operates that `agent_id` cannot yet query directly."""
    agent = state.agents[agent_id]
    return [
        s.id for s in scenario.public.sources
        if against in s.operators and source_mode(scenario, agent, s.id) != "direct"
    ]


def heard_statement(state: SimState, agent_id: str, voice: str, proposition: str) -> StatementState | None:
    """The first statement in which `agent_id` heard `voice` say `proposition`, directly or passed on."""
    for statement in sorted(state.statements.values(), key=lambda s: s.seq):
        if statement.recipient == agent_id and statement.proposition == proposition and (statement.origin or statement.speaker) == voice:
            return statement
    return None


def statement_grounds(scenario: Scenario, state: SimState, agent_id: str, action: Tell) -> tuple[str, list[str]]:
    """What the speaker has for what it is about to say. Read from the speaker's own knowledge only."""
    key = Proposition.parse(action.proposition).key
    if action.heard_from is not None:
        return "heard", [heard_statement(state, agent_id, action.heard_from, key).id]
    if any(p.key == key for p in observations_of(scenario, agent_id)):
        return "observed", []
    backing = sorted(
        e for e in state.agents[agent_id].holdings if any(p.key == key for p in scenario.evidence[e].asserts)
    )
    return ("held", backing) if backing else ("none", [])


def _check_topic(scenario: Scenario, state: SimState, agent_id: str, topic: str) -> None:
    _require(topic in known_entity_ids(scenario, state, agent_id), "unknown_topic", f"{agent_id} does not know of {topic!r}")


def validate_action(scenario: Scenario, state: SimState, agent_id: str, action: Any) -> None:
    _require(state.status == "running", "case_closed", "the case is closed")
    agent = state.agents[agent_id]
    spec = scenario.agents[agent_id]

    if isinstance(action, Wait):
        return

    if isinstance(action, Inspect):
        source = scenario.sources.get(action.source)
        _require(source is not None, "unknown_source", f"no such source: {action.source!r}")
        _require(source_mode(scenario, agent, action.source) == "direct", "no_access", f"{agent_id} cannot query {action.source} directly")
        _check_topic(scenario, state, agent_id, action.topic)
        _require(action.topic in source.searchable, "not_searchable", f"{action.source} cannot be searched for {action.topic!r}")
        return

    if isinstance(action, Request):
        _require(action.to in scenario.agents, "unknown_agent", f"no such agent: {action.to!r}")
        _require(action.to != agent_id, "self_request", "an agent cannot send a request to itself")
        _check_topic(scenario, state, agent_id, action.topic)
        if action.source is not None:
            source = scenario.sources.get(action.source)
            _require(source is not None, "unknown_source", f"no such source: {action.source!r}")
            _require(agent_id in source.requesters, "not_authorized", f"{agent_id} may not request queries of {action.source}")
            _require(action.to in source.operators, "not_operator", f"{action.to} does not operate {action.source}")
            _require(action.topic in source.searchable, "not_searchable", f"{action.source} cannot be searched for {action.topic!r}")
        duplicate = any(
            r.status == "pending" and r.sender == agent_id and r.recipient == action.to
            and r.topic == action.topic and r.source == action.source
            for r in state.requests.values()
        )
        _require(not duplicate, "duplicate_request", "an identical request is still pending")
        return

    if isinstance(action, Respond):
        request = state.requests.get(action.request_id)
        _require(request is not None, "unknown_request", f"no such request: {action.request_id!r}")
        _require(request.recipient == agent_id, "not_addressee", "the request is addressed to someone else")
        _require(request.status == "pending", "already_answered", "the request has already been answered")
        if action.withhold_about:
            _require(action.accept, "malformed_response", "a declined request has nothing to hold back")
            known = known_entity_ids(scenario, state, agent_id)
            for entity_id in action.withhold_about:
                _require(entity_id in known, "unknown_topic", f"{agent_id} does not know of {entity_id!r}")
        return

    if isinstance(action, Share):
        _require(action.to in scenario.agents and action.to != agent_id, "unknown_agent", f"cannot share with {action.to!r}")
        _require(action.evidence_id in agent.holdings, "not_held", f"{agent_id} does not hold {action.evidence_id!r}")
        _require(scenario.evidence[action.evidence_id].shareable, "not_shareable", "this record is protected and cannot be passed on")
        _require(f"{action.to}|{action.evidence_id}" not in agent.shared, "already_shared", "already shared with this agent")
        return

    if isinstance(action, Publish):
        _require(spec.disposition.can_publish, "not_permitted", f"{agent_id} has no channel to publish claims")
        try:
            prop = Proposition.parse(action.proposition)
        except ValueError as exc:
            raise ActionError("malformed_proposition", str(exc)) from exc
        _require(prop.predicate in PUBLISHABLE_PREDICATES, "not_publishable", f"{prop.predicate} is not a publishable kind of claim")
        known = known_entity_ids(scenario, state, agent_id)
        for arg, kind in zip(prop.args, PREDICATES[prop.predicate]):
            entity = scenario.entities.get(arg)
            _require(arg in known and entity is not None and entity.kind == kind, "malformed_proposition", f"{arg!r} is not a known {kind}")
        _require(all(c in agent.holdings for c in action.cited), "not_held", "cited evidence must be held by the publisher")
        already = any(c.by == agent_id and c.status == "active" and c.proposition == prop.key for c in state.claims.values())
        _require(not already, "duplicate_claim", "the same claim is already published and active")
        return

    if isinstance(action, Retract):
        claim = state.claims.get(action.claim_id)
        _require(claim is not None, "unknown_claim", f"no such claim: {action.claim_id!r}")
        _require(claim.by == agent_id, "not_author", "only the author may retract a claim")
        _require(claim.status == "active", "already_retracted", "the claim is already retracted")
        return

    if isinstance(action, Accuse):
        _require(spec.disposition.can_accuse, "not_permitted", f"{agent_id} has no authority to accuse")
        _require(action.suspect in scenario.case.suspects, "not_a_suspect", f"{action.suspect!r} is not a suspect in this case")
        _require(all(c in agent.holdings for c in action.cited), "not_held", "cited evidence must be held by the accuser")
        return

    if isinstance(action, Tell):
        _require(action.to in scenario.agents and action.to != agent_id, "unknown_agent", f"cannot tell {action.to!r} anything")
        try:
            prop = Proposition.parse(action.proposition)
        except ValueError as exc:
            raise ActionError("malformed_proposition", str(exc)) from exc
        _require(prop.predicate in TELLABLE_PREDICATES, "not_tellable", f"{prop.predicate} is not something an agent can state on its own word")
        # A speaker can say anything about what it knows of, true or not. It cannot name
        # a person, place or time it has never come across.
        known = known_entity_ids(scenario, state, agent_id)
        for arg, kind in zip(prop.args, PREDICATES[prop.predicate]):
            if kind == "slot":
                _require(arg in scenario.slots, "malformed_proposition", f"{arg!r} is not a known time")
            else:
                entity = scenario.entities.get(arg)
                _require(arg in known and entity is not None and entity.kind == kind, "unknown_topic", f"{agent_id} does not know of a {kind} {arg!r}")
        if action.heard_from is not None:
            _require(action.heard_from != agent_id, "malformed_statement", "an agent does not report its own words as someone else's")
            _require(action.heard_from != action.to, "malformed_statement", "nobody needs their own words reported back to them")
            _require(
                heard_statement(state, agent_id, action.heard_from, prop.key) is not None,
                "not_heard", f"{agent_id} never heard {action.heard_from!r} say that",
            )
        voice = action.heard_from or agent_id
        already = any(
            s.speaker == agent_id and s.recipient == action.to and s.proposition == prop.key and (s.origin or s.speaker) == voice
            for s in state.statements.values()
        )
        _require(not already, "already_told", "already said to this agent")
        return

    if isinstance(action, Escalate):
        _require(spec.disposition.can_compel, "not_permitted", f"{agent_id} has no authority to take over a source")
        _require(action.against in scenario.agents and action.against != agent_id, "unknown_agent", f"cannot escalate against {action.against!r}")
        _require(bool(escalation_grounds(state, agent_id, action.against)), "no_grounds", f"{agent_id} has no grounds against {action.against}")
        _require(bool(escalation_targets(scenario, state, agent_id, action.against)), "nothing_to_escalate", f"{agent_id} already has direct access to everything {action.against} operates")
        return

    raise ActionError("unknown_action", f"unsupported action: {action!r}")


def _mark(dirty: Dirty, agent_id: str, ref: str) -> None:
    refs = dirty.setdefault(agent_id, [])
    if ref not in refs:
        refs.append(ref)


def apply_action(scenario: Scenario, state: SimState, agent_id: str, action: Any, emit: Emit) -> Dirty:
    """Emit the effects of a validated action. Returns who learned what."""
    dirty: Dirty = {}
    agent = state.agents[agent_id]

    if isinstance(action, Wait):
        return dirty

    if isinstance(action, Inspect):
        found = query_source(scenario, action.source, action.topic, set(agent.holdings))
        new = [e for e in found if e not in agent.holdings]
        emit("SourceInspected", agent_id, {"agent": agent_id, "source": action.source, "topic": action.topic, "found": found, "new": new})
        for evidence_id in new:
            emit("EvidenceObserved", agent_id, {"agent": agent_id, "evidence": evidence_id, "source": action.source, "via": "inspect"})
            _mark(dirty, agent_id, evidence_id)
        return dirty

    if isinstance(action, Request):
        # The request id is the seq this event will get: stable and unique without a counter.
        request_id = f"R{state.seq + 1}"
        emit("RequestSent", agent_id, {"request": request_id, "sender": agent_id, "recipient": action.to, "topic": action.topic, "source": action.source})
        return dirty

    if isinstance(action, Respond):
        request = state.requests[action.request_id]
        requester = state.agents[request.sender]
        if not action.accept:
            emit("RequestAnswered", agent_id, {"request": request.id, "by": agent_id, "outcome": "declined", "evidence": []})
            return dirty
        context = f"request:{request.id}"
        if request.source is not None:
            # A request carries its reason, so prerequisites may be met by either side.
            found = query_source(scenario, request.source, request.topic, set(agent.holdings) | set(requester.holdings))
            new = [e for e in found if e not in agent.holdings]
            emit("SourceInspected", agent_id, {
                "agent": agent_id, "source": request.source, "topic": request.topic,
                "found": found, "new": new, "on_behalf_of": request.sender,
            })
            for evidence_id in new:
                emit("EvidenceObserved", agent_id, {"agent": agent_id, "evidence": evidence_id, "source": request.source, "via": "inspect"})
                _mark(dirty, agent_id, evidence_id)
            handed_over = found
        else:
            handed_over = sorted(
                e for e in agent.holdings
                if request.topic in scenario.evidence[e].mentions and scenario.evidence[e].shareable
            )
        quiet = set(action.withhold_about)
        delivered = []
        withheld = []
        for evidence_id in handed_over:
            if not scenario.evidence[evidence_id].shareable:
                continue
            if quiet & set(scenario.evidence[evidence_id].mentions):
                withheld.append(evidence_id)
                continue
            delivered.append(evidence_id)
            if evidence_id not in requester.holdings:
                emit("EvidenceShared", agent_id, {"sender": agent_id, "recipient": request.sender, "evidence": evidence_id, "context": context})
                _mark(dirty, request.sender, evidence_id)
        if withheld:
            # The answer below does not mention this; the requester sees only what was delivered.
            emit("EvidenceWithheld", agent_id, {
                "request": request.id, "by": agent_id, "requester": request.sender,
                "evidence": withheld, "about": sorted(quiet),
            })
        emit("RequestAnswered", agent_id, {
            "request": request.id, "by": agent_id,
            "outcome": "fulfilled" if delivered else "nothing_found", "evidence": delivered,
        })
        return dirty

    if isinstance(action, Share):
        emit("EvidenceShared", agent_id, {"sender": agent_id, "recipient": action.to, "evidence": action.evidence_id, "context": "proactive"})
        _mark(dirty, action.to, action.evidence_id)
        return dirty

    if isinstance(action, Publish):
        claim_id = f"C{state.seq + 1}"
        audience = [a for a in scenario.agent_ids if a != agent_id]
        emit("ClaimPublished", agent_id, {
            "claim": claim_id, "by": agent_id, "proposition": Proposition.parse(action.proposition).key,
            "cited": list(action.cited), "audience": audience,
        })
        for listener in audience:
            _mark(dirty, listener, claim_id)
        return dirty

    if isinstance(action, Retract):
        claim = state.claims[action.claim_id]
        emit("ClaimRetracted", agent_id, {"claim": claim.id, "by": agent_id})
        for listener in claim.audience:
            _mark(dirty, listener, claim.id)
        return dirty

    if isinstance(action, Tell):
        statement_id = f"S{state.seq + 1}"
        grounds, backing = statement_grounds(scenario, state, agent_id, action)
        relayed = heard_statement(state, agent_id, action.heard_from, Proposition.parse(action.proposition).key) if action.heard_from else None
        emit("StatementMade", agent_id, {
            "statement": statement_id, "speaker": agent_id, "recipient": action.to,
            "proposition": Proposition.parse(action.proposition).key,
            "origin": action.heard_from, "relays": relayed.id if relayed else None,
            "grounds": grounds, "backing": backing,
        })
        _mark(dirty, action.to, statement_id)
        return dirty

    if isinstance(action, Escalate):
        grounds = escalation_grounds(state, agent_id, action.against)
        for source_id in escalation_targets(scenario, state, agent_id, action.against):
            emit("AccessEscalated", agent_id, {"agent": agent_id, "source": source_id, "against": action.against, "grounds": grounds})
        return dirty

    if isinstance(action, Accuse):
        emit("AccusationMade", agent_id, {"by": agent_id, "suspect": action.suspect, "cited": list(action.cited)})
        emit("CaseClosed", "engine", {"reason": "accusation"})
        return dirty

    raise ActionError("unknown_action", f"unsupported action: {action!r}")
