"""The observer view: what the API may show a human watching a run.

The observer sees the union of what the agents know, plus public scenario
data. It never sees undiscovered evidence (only how many records exist) and
never sees the truth block. Evaluation is gated separately in the service.

Statements follow from that: what was said, by whom, to whom, what the
speaker had for it and what the listener made of it are all things some agent
knows. Whether a statement was true is not, and is never part of a snapshot.

Deception follows the same rule. What a deceptive agent *did* is agent
knowledge and is shown: the records it held back, in the request list and the
event log. Why it did so, its scenario-private agenda, is not: `agendas()` is
called by the service only once a run is unlocked.
"""

from __future__ import annotations

from typing import Any

from .models import Event, Proposition
from .narrate import describe_proposition, narrate
from .policies import POLICY_INFO
from .scenario import Scenario
from .state import SimState
from .views import observation_id, observations_of, source_mode

STATUS_ORDER = {"believed": 0, "disputed": 1, "tentative": 2, "rejected": 3, "withdrawn": 4}


def scenario_summary(scenario: Scenario) -> dict[str, Any]:
    case = scenario.case
    return {
        "id": scenario.id,
        "version": scenario.version,
        "title": case.title,
        "briefing": case.briefing,
        "max_ticks": case.max_ticks,
        "evidence_total": len(scenario.evidence),
        "agents": [
            {"id": a.id, "name": scenario.entities[a.id].name, "role": a.role, "goals": list(a.goals)}
            for a in scenario.public.agents
        ],
        "suspects": [{"id": s, "name": scenario.entities[s].name} for s in case.suspects],
        "interventions": [
            {"id": i.id, "label": i.label, "description": i.description, "kind": i.kind}
            for i in scenario.public.interventions
        ],
        "policies": POLICY_INFO,
    }


def agendas(scenario: Scenario, state: SimState) -> dict[str, Any]:
    """Private agendas, for the service to attach once the solution may be shown."""
    return {
        agent_id: {**agenda.model_dump(mode="json"), "policy": state.agents[agent_id].policy}
        for agent_id, agenda in sorted(scenario.private.agendas.items())
    }


def observed_entity_ids(scenario: Scenario, state: SimState) -> set[str]:
    known = set(scenario.public_entity_ids)
    for evidence_id in state.discovered:
        known.update(scenario.evidence[evidence_id].mentions)
    for claim in state.claims.values():
        known.update(arg for arg in Proposition.parse(claim.proposition).args if arg in scenario.entities)
    for statement in state.statements.values():
        known.update(arg for arg in Proposition.parse(statement.proposition).args if arg in scenario.entities)
    for agent_id in scenario.agent_ids:
        for prop in observations_of(scenario, agent_id):
            known.update(arg for arg in prop.args if arg in scenario.entities)
    return known


def event_rows(scenario: Scenario, events: list[Event]) -> list[dict[str, Any]]:
    return [
        {**event.body(), "hash": event.hash, "summary": narrate(scenario, event)}
        for event in events
    ]


def snapshot(scenario: Scenario, state: SimState) -> dict[str, Any]:
    """Everything the interface needs to draw one tick of a run."""
    known = observed_entity_ids(scenario, state)
    texts: dict[str, str] = {}

    def text(key: str) -> str:
        if key not in texts:
            texts[key] = describe_proposition(scenario, key)
        return texts[key]

    evidence: dict[str, Any] = {}
    for evidence_id, discovery in sorted(state.discovered.items(), key=lambda item: item[1].seq):
        spec = scenario.evidence[evidence_id]
        evidence[evidence_id] = {
            "id": spec.id,
            "title": spec.title,
            "text": spec.text,
            "kind": spec.kind,
            "speaker": spec.speaker,
            "source": spec.source,
            "source_name": scenario.sources[spec.source].name,
            "mentions": list(spec.mentions),
            "asserts": [{"key": p.key, "text": text(p.key)} for p in spec.asserts],
            "shareable": spec.shareable,
            "discovered_by": discovery.by,
            "discovered_tick": discovery.tick,
            "discovered_via": discovery.via,
            "holders": sorted(a.id for a in state.agents.values() if evidence_id in a.holdings),
        }

    agents = []
    for spec in scenario.public.agents:
        agent = state.agents[spec.id]
        beliefs = [
            {
                "key": key,
                "text": text(key),
                "predicate": Proposition.parse(key).predicate,
                "status": belief.status,
                "support": belief.support,
                "contra": belief.contra,
                "evidence": list(belief.evidence),
                "against": list(belief.against),
                "derivations": [d.model_dump(mode="json") for d in belief.derivations],
            }
            for key, belief in agent.beliefs.items()
        ]
        beliefs.sort(key=lambda b: (STATUS_ORDER[b["status"]], -b["support"], b["key"]))
        for belief in beliefs:
            for derivation in belief["derivations"]:
                for premise in derivation["premises"]:
                    text(premise)
                if derivation["defeated_by"]:
                    text(derivation["defeated_by"])
        agents.append({
            "id": spec.id,
            "name": scenario.entities[spec.id].name,
            "role": spec.role,
            "goals": list(spec.goals),
            "policy": agent.policy,
            "disposition": spec.disposition.model_dump(mode="json"),
            "prime_suspect": agent.prime_suspect,
            "suspects": {name: a.model_dump(mode="json") for name, a in agent.suspects.items()},
            "beliefs": beliefs,
            "holdings": [
                {"id": h.evidence, "tick": h.tick, "seq": h.seq, "via": h.via, "from_agent": h.from_agent, "chain": h.chain}
                for h in sorted(agent.holdings.values(), key=lambda h: h.seq)
            ],
            "contradictions": [
                {"pair": pair, "a": text(pair.split("|")[0]), "b": text(pair.split("|")[1])} for pair in agent.contradictions
            ],
            "sources": [
                {"id": s.id, "name": s.name, "mode": source_mode(scenario, agent, s.id)}
                for s in scenario.public.sources
                if source_mode(scenario, agent, s.id) != "none"
            ],
            "actions": agent.actions,
            "rejected": agent.rejected,
            "discrepancies": [
                {"against": d.against, "request": d.request, "evidence": d.evidence, "tick": d.tick, "seq": d.seq}
                for d in agent.discrepancies
            ],
            "escalated": list(agent.escalated),
            "observations": [
                {"id": observation_id(index), "key": prop.key, "text": text(prop.key)}
                for index, prop in enumerate(observations_of(scenario, spec.id))
            ],
            "credibility": [
                {
                    "speaker": speaker,
                    "name": scenario.entities[speaker].name if speaker in scenario.entities else speaker,
                    "standing": seen.current.standing,
                    "refuted": [{"key": key, "text": text(key)} for key in seen.current.refuted],
                    "corroborated": [{"key": key, "text": text(key)} for key in seen.current.corroborated],
                    "history": [h.model_dump(mode="json") for h in seen.history],
                }
                for speaker, seen in sorted(agent.credibility.items()) if seen.current is not None
            ],
        })

    claims = [
        {
            "id": claim.id,
            "by": claim.by,
            "proposition": claim.proposition,
            "text": text(claim.proposition),
            "quote": claim.text,
            "cited": claim.cited,
            "audience": claim.audience,
            "tick": claim.tick,
            "status": claim.status,
            "retracted_tick": claim.retracted_tick,
        }
        for claim in sorted(state.claims.values(), key=lambda c: c.seq)
    ]
    requests = [
        {
            "id": r.id, "sender": r.sender, "recipient": r.recipient, "topic": r.topic, "source": r.source,
            "source_name": scenario.sources[r.source].name if r.source else None,
            "tick": r.tick, "status": r.status, "answered_tick": r.answered_tick, "evidence": r.evidence,
            # Known to the responder, so the observer sees it. The requester's own view never does.
            "withheld": r.withheld,
        }
        for r in sorted(state.requests.values(), key=lambda r: r.seq)
    ]
    statements = [
        {
            "id": s.id, "speaker": s.speaker, "recipient": s.recipient, "proposition": s.proposition,
            "text": text(s.proposition), "origin": s.origin, "relays": s.relays, "tick": s.tick, "seq": s.seq,
            # Known to the speaker, so the observer sees it. The recipient's own view never does.
            "grounds": s.grounds, "backing": s.backing,
            "stance": s.stances[-1].stance if s.stances else None,
            "stances": [c.model_dump(mode="json") for c in s.stances],
        }
        for s in sorted(state.statements.values(), key=lambda s: s.seq)
    ]
    case = scenario.case
    return {
        "tick": state.tick,
        "seq": state.seq,
        "status": state.status,
        "close_reason": state.close_reason,
        "accusation": state.accusation,
        "case": {
            "title": case.title,
            "briefing": case.briefing,
            "object": case.object,
            "crime_location": case.crime_location,
            "suspects": list(case.suspects),
            "max_ticks": case.max_ticks,
        },
        "entities": {
            e: {"id": e, "kind": scenario.entities[e].kind, "name": scenario.entities[e].name, "description": scenario.entities[e].description}
            for e in sorted(known)
        },
        "sources": {
            s.id: {
                "id": s.id, "name": s.name, "kind": s.kind, "description": s.description,
                "operators": list(s.operators), "requesters": list(s.requesters), "self_serve": s.self_serve,
            }
            for s in scenario.public.sources
        },
        "agents": agents,
        "evidence": evidence,
        "evidence_total": len(scenario.evidence),
        "claims": claims,
        "requests": requests,
        "statements": statements,
        "interventions": [
            {"id": i.id, "label": i.label, "description": i.description, "kind": i.kind, "applied": i.id in state.interventions}
            for i in scenario.public.interventions
        ],
        "propositions": dict(sorted(texts.items())),
    }
