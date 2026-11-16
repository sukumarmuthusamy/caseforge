"""The policy seam.

A policy sees an `AgentView` and returns a `Decision`. It never sees the
engine, the scenario or the world state. `legal_actions` enumerates the moves
that are structurally available from a view; it is shared by every policy so
that an LLM policy chooses from the same menu the baseline does.
"""

from __future__ import annotations

from typing import Protocol

from ..canon import DeterministicRng
from ..models import (
    TELLABLE_PREDICATES,
    Accuse,
    AgentView,
    Decision,
    Escalate,
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


class Policy(Protocol):
    name: str
    deterministic: bool

    def decide(self, view: AgentView, rng: DeterministicRng) -> Decision: ...


def legal_actions(view: AgentView) -> list:
    """Every action worth offering from this view, in a stable order.

    The engine still validates whatever is chosen: this list is a menu, not a
    permission system.
    """
    me = view.me
    held = {e.id for e in view.evidence}
    actions: list = []

    for request in view.inbox:
        actions.append(Respond(request_id=request.id, accept=True))
        actions.append(Respond(request_id=request.id, accept=False))

    if me.disposition.can_accuse:
        for suspect in view.case.suspects:
            assessment = view.suspects.get(suspect)
            cited = tuple(e for e in (assessment.evidence if assessment else ()) if e in held)
            actions.append(Accuse(suspect=suspect, cited=cited))

    if me.disposition.can_compel:
        for other in view.roster:
            if other.id != me.id and grounds_against(view, other.id) and any(
                other.id in s.operators and s.mode != "direct" for s in view.sources
            ):
                actions.append(Escalate(against=other.id))

    for claim in view.claims:
        if claim.mine and claim.status == "active":
            actions.append(Retract(claim_id=claim.id))

    if me.disposition.can_publish:
        active = {c.proposition for c in view.claims if c.mine and c.status == "active"}
        for suspect in view.case.suspects:
            for key in (f"has_motive({suspect})", f"took({suspect},{view.case.object})"):
                belief = view.beliefs.get(key)
                if belief is None or belief.support <= 0 or key in active:
                    continue
                actions.append(Publish(proposition=key, cited=tuple(e for e in belief.evidence if e in held)))

    already_shared = set(view.shared)
    for other in view.roster:
        if other.id == me.id:
            continue
        for evidence in view.evidence:
            if evidence.shareable and evidence.from_agent != other.id and f"{other.id}|{evidence.id}" not in already_shared:
                actions.append(Share(to=other.id, evidence_id=evidence.id))

    pending = {(r.recipient, r.source, r.topic) for r in view.outbox if r.status == "pending"}
    for source in view.sources:
        for topic in source.searchable:
            if source.mode == "direct":
                actions.append(Inspect(source=source.id, topic=topic))
            elif source.mode == "request":
                # Every operator is offered: which one to ask is the policy's call.
                for operator in sorted(source.operators):
                    if operator != me.id and (operator, source.id, topic) not in pending:
                        actions.append(Request(to=operator, topic=topic, source=source.id))

    asked = {(r.recipient, r.topic) for r in view.outbox if r.source is None}
    for other in view.roster:
        if other.id == me.id:
            continue
        topics = [view.case.object] + ([other.id] if other.id in view.case.suspects else [])
        for topic in topics:
            if (other.id, topic) not in asked:
                actions.append(Request(to=other.id, topic=topic, source=None))

    # Saying what I saw, and passing on what I was told. Offered only where there is
    # something to say, so a case without observations has the menu it always had.
    told = {(s.recipient, s.proposition, s.origin or s.speaker) for s in view.statements if s.mine}
    for other in view.roster:
        if other.id == me.id:
            continue
        for key in view.observations:
            if Proposition.parse(key).predicate in TELLABLE_PREDICATES and (other.id, key, me.id) not in told:
                actions.append(Tell(to=other.id, proposition=key))
        offered = set()
        for statement in view.statements:
            voice = statement.origin or statement.speaker
            relay = (other.id, statement.proposition, voice)
            if statement.mine or other.id in (voice, statement.speaker) or relay in told or relay in offered:
                continue
            offered.add(relay)
            actions.append(Tell(to=other.id, proposition=statement.proposition, heard_from=voice))

    actions.append(Wait())
    return actions


def grounds_against(view: AgentView, other: str) -> tuple[str, ...]:
    """Request ids that give this agent cause to distrust `other` as an operator.

    The same two things the engine accepts for an escalation: an answer caught
    leaving a record out, and a refused search request.
    """
    caught = {d.request for d in view.discrepancies if d.against == other}
    refused = {r.id for r in view.outbox if r.recipient == other and r.source is not None and r.status == "declined"}
    return tuple(r.id for r in view.outbox if r.id in caught | refused)


def describe(action) -> str:
    """A compact one-line rendering of an action for traces and prompts."""
    data = action.model_dump(mode="json")
    kind = data.pop("type")
    parts = [f"{key}={value}" for key, value in data.items() if value not in (None, [], ())]
    return f"{kind}({', '.join(parts)})"
