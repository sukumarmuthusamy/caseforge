"""The observation gateway.

This is the only code that turns simulation state into something an agent may
see. Evidence bodies are resolved here and only for records the agent holds.
Nothing in this module reads `scenario.truth`.
"""

from __future__ import annotations

from .models import (
    AgentView,
    CaseView,
    ClaimView,
    Credibility,
    DiscrepancyView,
    Entity,
    EvidenceView,
    Proposition,
    RequestView,
    RosterEntry,
    SelfView,
    SourceView,
    StatementView,
    TriedView,
)
from .reasoning import Item, ReasoningContext
from .scenario import Scenario
from .state import AgentState, RequestState, SimState


class IsolationError(Exception):
    """Raised when code asks for evidence on behalf of an agent who does not hold it."""


def evidence_view(scenario: Scenario, agent: AgentState, evidence_id: str) -> EvidenceView:
    holding = agent.holdings.get(evidence_id)
    if holding is None:
        raise IsolationError(f"{agent.id} does not hold {evidence_id}")
    spec = scenario.evidence[evidence_id]
    return EvidenceView(
        id=spec.id,
        title=spec.title,
        text=spec.text,
        kind=spec.kind,
        speaker=spec.speaker,
        source=spec.source,
        mentions=spec.mentions,
        asserts=tuple(p.key for p in spec.asserts),
        shareable=spec.shareable,
        acquired_seq=holding.seq,
        acquired_tick=holding.tick,
        via=holding.via,
        from_agent=holding.from_agent,
        chain=tuple(holding.chain),
    )


def observations_of(scenario: Scenario, agent_id: str) -> tuple[Proposition, ...]:
    """What an agent saw for itself. Private scenario data: every caller asks on behalf of that agent."""
    return scenario.private.observations.get(agent_id, ())


def observation_id(index: int) -> str:
    """Item id of an agent's n-th observation. Local to that agent."""
    return f"O{index + 1}"


def known_entity_ids(scenario: Scenario, state: SimState, agent_id: str) -> set[str]:
    """Entities the agent knows exist: public ones plus any named in what it holds, saw or heard."""
    agent = state.agents[agent_id]
    known = set(scenario.public_entity_ids)
    for evidence_id in agent.holdings:
        known.update(scenario.evidence[evidence_id].mentions)
    for prop in observations_of(scenario, agent_id):
        known.update(arg for arg in prop.args if arg in scenario.entities)
    for statement in state.statements.values():
        if statement.recipient == agent_id:
            known.update(arg for arg in Proposition.parse(statement.proposition).args if arg in scenario.entities)
    for claim_id in agent.heard:
        prop = Proposition.parse(state.claims[claim_id].proposition)
        known.update(arg for arg in prop.args if arg in scenario.entities)
    return known


def items_for_agent(scenario: Scenario, state: SimState, agent_id: str, upto_seq: int | None = None) -> list[Item]:
    """Everything the agent can reason from: held evidence, what it saw, what it was told, active claims it heard.

    With `upto_seq`, reconstructs what the agent had at that point in the run.
    """
    agent = state.agents[agent_id]
    items: list[Item] = [
        Item(id=observation_id(index), kind="observation", speaker=agent_id, asserts=(prop,))
        for index, prop in enumerate(observations_of(scenario, agent_id))
    ]
    for statement in sorted(state.statements.values(), key=lambda s: s.seq):
        if statement.recipient == agent_id and (upto_seq is None or statement.seq <= upto_seq):
            items.append(Item(
                id=statement.id, kind="testimony", speaker=statement.speaker,
                asserts=(Proposition.parse(statement.proposition),), origin=statement.origin,
            ))
    for evidence_id, holding in sorted(agent.holdings.items()):
        if upto_seq is None or holding.seq <= upto_seq:
            items.append(scenario.item_for(evidence_id))
    for claim_id, heard_seq in sorted(agent.heard.items()):
        claim = state.claims[claim_id]
        if upto_seq is not None and heard_seq > upto_seq:
            continue
        retracted = claim.status == "retracted" and (upto_seq is None or (claim.retracted_seq or 0) <= upto_seq)
        if retracted or claim.by == agent_id:
            continue
        items.append(Item(id=claim.id, kind="hearsay", speaker=claim.by, asserts=(Proposition.parse(claim.proposition),)))
    return items


def context_for_agent(scenario: Scenario, agent_id: str) -> ReasoningContext:
    return scenario.reasoning_context(scenario.agents[agent_id].disposition.hearsay_weight)


def source_mode(scenario: Scenario, agent: AgentState, source_id: str) -> str:
    source = scenario.sources[source_id]
    if source_id in agent.granted or (agent.id in source.operators and source.self_serve):
        return "direct"
    if agent.id in source.requesters:
        return "request"
    return "none"


def _request_view(request: RequestState) -> RequestView:
    return RequestView(
        id=request.id,
        sender=request.sender,
        recipient=request.recipient,
        topic=request.topic,
        source=request.source,
        status=request.status,
        seq=request.seq,
        tick=request.tick,
        evidence=tuple(request.evidence),
    )


def build_view(scenario: Scenario, state: SimState, agent_id: str) -> AgentView:
    agent = state.agents[agent_id]
    spec = scenario.agents[agent_id]
    known = known_entity_ids(scenario, state, agent_id)

    entities: list[Entity] = [scenario.entities[e] for e in sorted(known)]
    sources = [
        SourceView(
            id=source.id,
            name=source.name,
            kind=source.kind,
            mode=source_mode(scenario, agent, source.id),
            operators=source.operators,
            searchable=tuple(topic for topic in source.searchable if topic in known),
        )
        for source in scenario.public.sources
    ]
    claims = [
        ClaimView(
            id=claim.id,
            by=claim.by,
            proposition=claim.proposition,
            cited=tuple(claim.cited),
            tick=claim.tick,
            status=claim.status,
            mine=claim.by == agent_id,
        )
        for claim in sorted(state.claims.values(), key=lambda c: c.seq)
        if claim.by == agent_id or claim.id in agent.heard
    ]
    requests = sorted(state.requests.values(), key=lambda r: r.seq)
    case = scenario.case
    view = AgentView(
        me=SelfView(
            id=agent_id,
            name=scenario.entities[agent_id].name,
            role=spec.role,
            goals=spec.goals,
            disposition=spec.disposition,
            # Private scenario data, delivered to its owner and nobody else.
            agenda=scenario.private.agendas.get(agent_id),
        ),
        tick=state.tick,
        case=CaseView(
            title=case.title,
            briefing=case.briefing,
            object=case.object,
            crime_location=case.crime_location,
            suspects=case.suspects,
            max_ticks=case.max_ticks,
        ),
        roster=tuple(
            RosterEntry(id=a.id, name=scenario.entities[a.id].name, role=a.role) for a in scenario.public.agents
        ),
        entities=tuple(entities),
        sources=tuple(sources),
        evidence=tuple(
            evidence_view(scenario, agent, evidence_id)
            for evidence_id in sorted(agent.holdings, key=lambda e: (agent.holdings[e].seq, e))
        ),
        claims=tuple(claims),
        beliefs=dict(agent.beliefs),
        suspects=dict(agent.suspects),
        prime_suspect=agent.prime_suspect,
        contradictions=tuple(agent.contradictions),
        tried={key: TriedView(seq=t.seq, found=t.found, count=t.count) for key, t in sorted(agent.tried.items())},
        inbox=tuple(_request_view(r) for r in requests if r.recipient == agent_id and r.status == "pending"),
        outbox=tuple(_request_view(r) for r in requests if r.sender == agent_id),
        shared=tuple(agent.shared),
        discrepancies=tuple(
            DiscrepancyView(against=d.against, request=d.request, evidence=d.evidence, seq=d.seq, tick=d.tick)
            for d in agent.discrepancies
        ),
        # Private scenario data, delivered to its owner and nobody else.
        observations=tuple(p.key for p in observations_of(scenario, agent_id)),
        # Both ends of a statement know it was made. What the speaker had for it stays with the speaker.
        statements=tuple(
            StatementView(
                id=s.id, speaker=s.speaker, recipient=s.recipient, proposition=s.proposition,
                origin=s.origin, seq=s.seq, tick=s.tick, mine=s.speaker == agent_id,
            )
            for s in sorted(state.statements.values(), key=lambda s: s.seq)
            if agent_id in (s.speaker, s.recipient)
        ),
        credibility={
            speaker: Credibility.model_validate(entry.current.model_dump())
            for speaker, entry in sorted(agent.credibility.items())
            if entry.current is not None
        },
    )
    # A deep copy through JSON: the policy gets values, never references into engine state.
    return AgentView.model_validate_json(view.model_dump_json())
