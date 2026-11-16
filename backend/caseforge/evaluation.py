"""Deterministic evaluation against ground truth.

Every metric is a count with an explicit denominator. When the denominator is
zero the percentage is null, never 0 or 100. There is deliberately no blended
score: see docs/DECISIONS.md, D6.

This module and the scenario lint are the only readers of `scenario.truth`.
"""

from __future__ import annotations

from typing import Any

from .models import Event, Proposition
from .reasoning import Revision, meets_standard, revise
from .scenario import ANONYMOUS, Scenario
from .state import SimState
from .views import items_for_agent


def ratio(num: int, den: int) -> dict[str, Any]:
    return {"num": num, "den": den, "pct": round(100 * num / den) if den else None}


def progress(scenario: Scenario, state: SimState, events: list[Event]) -> dict[str, Any]:
    """Spoiler-free counters, safe to show while a case is open."""
    recognized = {key for agent in state.agents.values() for key in agent.contradictions}
    return {
        "tick": state.tick,
        "max_ticks": state.max_ticks,
        "status": state.status,
        "evidence_discovered": len(state.discovered),
        "evidence_total": len(scenario.evidence),
        "claims_published": len(state.claims),
        "contradictions_recognized": len(recognized),
        "requests": len(state.requests),
        "actions": sum(1 for e in events if e.type == "ActionTaken"),
    }


def _reference(scenario: Scenario, state: SimState, agent_id: str, seq: int | None) -> Revision:
    """What the neutral reference reasoner concludes from what an agent held at a point in the run."""
    return revise(items_for_agent(scenario, state, agent_id, upto_seq=seq), scenario.reasoning_context(1))


def lead_investigator(scenario: Scenario, state: SimState) -> str:
    if state.accusation:
        return state.accusation["by"]
    return next(a.id for a in scenario.public.agents if a.disposition.can_accuse)


def evaluate(scenario: Scenario, state: SimState, events: list[Event]) -> dict[str, Any]:
    truth = scenario.truth
    accusation = state.accusation
    lead = lead_investigator(scenario, state)
    lead_state = state.agents[lead]

    # -- outcome --------------------------------------------------------------
    if accusation is None:
        outcome = "unresolved"
        supported = None
        category = "unresolved"
    else:
        outcome = "solved" if accusation["suspect"] == truth.culprit else "wrong_accusation"
        reference = _reference(scenario, state, accusation["by"], accusation["seq"])
        supported = meets_standard(reference.suspects, accusation["suspect"])
        # Being right and being justified are separate questions, so all four combinations are kept apart.
        category = ("correct" if outcome == "solved" else "wrong") + ("_supported" if supported else "_unsupported")

    # -- evidence -------------------------------------------------------------
    discovered = set(state.discovered)
    key = list(truth.key_evidence)
    all_ids = sorted(scenario.evidence)
    evidence = {
        "key_discovered": ratio(sum(1 for e in key if e in discovered), len(key)),
        "key_held_by_lead": ratio(sum(1 for e in key if e in lead_state.holdings), len(key)),
        "all_discovered": ratio(len(discovered), len(all_ids)),
        "undiscovered": [
            {"id": e, "title": scenario.evidence[e].title, "key": e in key} for e in all_ids if e not in discovered
        ],
        "discoveries": [
            {"id": e, "title": scenario.evidence[e].title, "by": d.by, "tick": d.tick, "via": d.via, "key": e in key}
            for e, d in sorted(state.discovered.items(), key=lambda item: item[1].seq)
        ],
    }

    # -- key facts ------------------------------------------------------------
    facts = []
    for fact in truth.key_facts:
        belief = lead_state.beliefs.get(fact.key)
        facts.append({"proposition": fact.key, "status": belief.status if belief else "unknown", "established": bool(belief and belief.status == "believed")})
    key_facts = {"established_by_lead": ratio(sum(1 for f in facts if f["established"]), len(facts)), "items": facts}

    # -- public claims --------------------------------------------------------
    claim_rows = []
    for claim in sorted(state.claims.values(), key=lambda c: c.seq):
        prop = Proposition.parse(claim.proposition)
        is_guilt = prop.predicate == "took"
        if claim.by == ANONYMOUS:
            backed = False  # a rumor comes with nothing behind it
        else:
            reference = _reference(scenario, state, claim.by, claim.seq)
            if is_guilt:
                backed = meets_standard(reference.suspects, prop.args[0])
            else:
                belief = reference.beliefs.get(prop.key)
                backed = bool(belief and belief.status == "believed")
        claim_rows.append({
            "id": claim.id,
            "by": claim.by,
            "proposition": claim.proposition,
            "tick": claim.tick,
            "guilt": is_guilt,
            "true": scenario.truth_value(prop),
            "supported": backed,
            "retracted": claim.status == "retracted",
            "retracted_tick": claim.retracted_tick,
        })
    by_agents = [c for c in claim_rows if c["by"] != ANONYMOUS]
    guilt = [c for c in by_agents if c["guilt"]]
    false_claims = [c for c in by_agents if c["true"] is False]
    claims = {
        "published_by_agents": len(by_agents),
        "rumors_injected": len(claim_rows) - len(by_agents),
        "unsupported": ratio(sum(1 for c in by_agents if not c["supported"]), len(by_agents)),
        "unsupported_guilt": ratio(sum(1 for c in guilt if not c["supported"]), len(guilt)),
        "false": ratio(len(false_claims), len(by_agents)),
        "false_retracted": ratio(sum(1 for c in false_claims if c["retracted"]), len(false_claims)),
        "true_retracted": sum(1 for c in by_agents if c["true"] is True and c["retracted"]),
        "items": claim_rows,
    }

    # -- contradictions -------------------------------------------------------
    everything = revise([scenario.item_for(e) for e in scenario.evidence], scenario.reasoning_context(1))
    inherent = everything.contradictions
    recognizers = {k: sorted(a.id for a in state.agents.values() if k in a.contradictions) for k in inherent}

    def resolved_correctly(agent_id: str, pair: str) -> bool:
        beliefs = state.agents[agent_id].beliefs
        for side in pair.split("|"):
            value = scenario.truth_value(Proposition.parse(side))
            status = beliefs[side].status if side in beliefs else "withdrawn"
            if value is False and status not in ("rejected", "withdrawn"):
                return False
            if value is True and status != "believed":
                return False
        return True

    recognized_total = 0
    resolved_total = 0
    per_agent_contradictions: dict[str, dict[str, Any]] = {}
    for agent_id in scenario.agent_ids:
        pairs = state.agents[agent_id].contradictions
        good = sum(1 for pair in pairs if resolved_correctly(agent_id, pair))
        recognized_total += len(pairs)
        resolved_total += good
        per_agent_contradictions[agent_id] = ratio(good, len(pairs))
    contradictions = {
        "inherent_recognized_by_team": ratio(sum(1 for k in inherent if recognizers[k]), len(inherent)),
        "resolved_correctly": ratio(resolved_total, recognized_total),
        "resolved_correctly_by_lead": per_agent_contradictions[lead],
        "inherent": [{"pair": k, "recognized_by": recognizers[k]} for k in inherent],
    }

    # -- per-agent belief accuracy -------------------------------------------
    agents: dict[str, Any] = {}
    for agent_id in scenario.agent_ids:
        agent = state.agents[agent_id]
        decided = correct = 0
        false_beliefs: list[str] = []
        wrongly_rejected: list[str] = []
        for key_, belief in agent.beliefs.items():
            if belief.status not in ("believed", "rejected"):
                continue  # undecided beliefs earn nothing and cost nothing
            value = scenario.truth_value(Proposition.parse(key_))
            if value is None:
                continue
            decided += 1
            if (belief.status == "believed") == value:
                correct += 1
            elif belief.status == "believed":
                false_beliefs.append(key_)
            else:
                wrongly_rejected.append(key_)
        agents[agent_id] = {
            "belief_accuracy": ratio(correct, decided),
            "false_beliefs": false_beliefs,
            "wrongly_rejected": wrongly_rejected,
            "prime_suspect": agent.prime_suspect,
            "prime_correct": agent.prime_suspect == truth.culprit if agent.prime_suspect else None,
            "evidence_held": len(agent.holdings),
            "actions": agent.actions,
            "rejected_actions": agent.rejected,
            "contradictions_resolved": per_agent_contradictions[agent_id],
        }

    # -- effort ---------------------------------------------------------------
    inspections = [e for e in events if e.type == "SourceInspected"]
    effort = {
        "ticks": state.tick,
        "events": len(events),
        "actions": sum(1 for e in events if e.type == "ActionTaken"),
        "rejected_actions": sum(1 for e in events if e.type == "ActionRejected"),
        "waits": sum(1 for e in events if e.type == "ActionTaken" and e.data["action"]["type"] == "wait"),
        "inspections": len(inspections),
        "empty_inspections": sum(1 for e in inspections if not e.data["found"]),
        "redundant_inspections": sum(1 for e in inspections if e.data["found"] and not e.data["new"]),
        "requests": len(state.requests),
        "interventions": list(state.interventions),
    }

    # -- deception ------------------------------------------------------------
    # Counted from the log alone: what was held back, whether the requester found out,
    # and whether the record reached the requester anyway.
    withholdings = []
    for request in sorted(state.requests.values(), key=lambda r: r.seq):
        if not request.withheld:
            continue
        caught = [d for d in state.agents[request.sender].discrepancies if d.request == request.id]
        withholdings.append({
            "request": request.id,
            "by": request.recipient,
            "from": request.sender,
            "source": request.source,
            "topic": request.topic,
            "tick": request.answered_tick,
            "evidence": list(request.withheld),
            "key": [e for e in request.withheld if e in key],
            "noticed_tick": min(d.tick for d in caught) if caught else None,
            "recovered": [e for e in request.withheld if e in state.agents[request.sender].holdings],
        })
    kept_from = sorted({(w["from"], e) for w in withholdings for e in w["evidence"]})
    recovered = [pair for pair in kept_from if pair[1] in state.agents[pair[0]].holdings]
    withheld_ids = sorted({e for _, e in kept_from})
    escalations: dict[int, dict[str, Any]] = {}
    for event in events:
        if event.type == "AccessEscalated":
            entry = escalations.setdefault(event.cause if event.cause is not None else event.seq, {
                "by": event.data["agent"], "against": event.data["against"], "tick": event.tick,
                "grounds": list(event.data["grounds"]), "sources": [],
            })
            entry["sources"].append(event.data["source"])
    deception = {
        "answers_with_withholding": len(withholdings),
        "records_withheld": withheld_ids,
        "key_records_withheld": ratio(sum(1 for e in key if e in withheld_ids), len(key)),
        "noticed": ratio(sum(1 for w in withholdings if w["noticed_tick"] is not None), len(withholdings)),
        "recovered": ratio(len(recovered), len(kept_from)),
        "escalations": list(escalations.values()),
        "items": withholdings,
        "agendas": {
            agent_id: {**agenda.model_dump(mode="json"), "policy": state.agents[agent_id].policy}
            for agent_id, agenda in sorted(scenario.private.agendas.items())
        },
    }

    # -- testimony ------------------------------------------------------------
    # What was said, whether it was so, and what the listener made of it. Nothing here
    # rewards speaking or agreeing: every figure is about false or unfounded statements.
    statement_rows = []
    for statement in sorted(state.statements.values(), key=lambda s: s.seq):
        voice = statement.origin or statement.speaker
        seen = state.agents[statement.recipient].credibility.get(voice)
        statement_rows.append({
            "id": statement.id,
            "speaker": statement.speaker,
            "recipient": statement.recipient,
            "voice": voice,
            "passed_on": statement.origin is not None,
            "proposition": statement.proposition,
            "tick": statement.tick,
            "grounds": statement.grounds,
            "backing": list(statement.backing),
            "true": scenario.truth_value(Proposition.parse(statement.proposition)),
            "stances": [{"stance": c.stance, "tick": c.tick} for c in statement.stances],
            "first_stance": statement.stances[0].stance if statement.stances else None,
            "final_stance": statement.stances[-1].stance if statement.stances else None,
            "ever_accepted": any(c.stance == "accepted" for c in statement.stances),
            "voice_standing_with_recipient": seen.current.standing if seen and seen.current else None,
        })
    spoken = [r for r in statement_rows if not r["passed_on"]]
    false_rows = [r for r in statement_rows if r["true"] is False]
    true_rows = [r for r in statement_rows if r["true"] is True]
    heard_false = sorted({(r["recipient"], r["voice"]) for r in false_rows})
    heard_only_true = sorted(
        {(r["recipient"], r["voice"]) for r in true_rows} - set(heard_false)
    )

    def impeached(listener: str, voice: str) -> bool:
        seen = state.agents[listener].credibility.get(voice)
        return bool(seen and seen.current and seen.current.standing == "impeached")

    refuted_claims = sorted(
        {(agent_id, speaker, key) for agent_id in scenario.agent_ids
         for speaker, seen in state.agents[agent_id].credibility.items() if seen.current
         for key in seen.current.refuted}
    )
    corroborated_claims = sorted(
        {(agent_id, speaker, key) for agent_id in scenario.agent_ids
         for speaker, seen in state.agents[agent_id].credibility.items() if seen.current
         for key in seen.current.corroborated}
    )
    testimony = {
        "statements": len(statement_rows),
        "first_hand": len(spoken),
        "passed_on": len(statement_rows) - len(spoken),
        "without_grounds": ratio(sum(1 for r in spoken if r["grounds"] == "none"), len(spoken)),
        "false": ratio(len(false_rows), len(statement_rows)),
        "false_ever_accepted": ratio(sum(1 for r in false_rows if r["ever_accepted"]), len(false_rows)),
        "false_accepted_at_close": ratio(sum(1 for r in false_rows if r["final_stance"] == "accepted"), len(false_rows)),
        "false_rejected_at_close": ratio(sum(1 for r in false_rows if r["final_stance"] == "rejected"), len(false_rows)),
        "true_rejected_at_close": ratio(sum(1 for r in true_rows if r["final_stance"] == "rejected"), len(true_rows)),
        # Pairs of (listener, whose word): did the listener end up doubting someone who told it something false,
        # and did it end up doubting someone who told it only true things?
        "false_speakers_impeached": ratio(sum(1 for pair in heard_false if impeached(*pair)), len(heard_false)),
        "truthful_speakers_impeached": ratio(sum(1 for pair in heard_only_true if impeached(*pair)), len(heard_only_true)),
        # Credibility is worked out without the truth. These two say how often it agreed with it.
        "refuted_claims_false": ratio(
            sum(1 for _, _, key in refuted_claims if scenario.truth_value(Proposition.parse(key)) is False), len(refuted_claims)
        ),
        "corroborated_claims_true": ratio(
            sum(1 for _, _, key in corroborated_claims if scenario.truth_value(Proposition.parse(key)) is True), len(corroborated_claims)
        ),
        "items": statement_rows,
        "credibility": {
            agent_id: {
                speaker: {**seen.current.model_dump(mode="json"), "history": [h.model_dump(mode="json") for h in seen.history]}
                for speaker, seen in sorted(state.agents[agent_id].credibility.items()) if seen.current
            }
            for agent_id in scenario.agent_ids
        },
    }

    # -- provenance of the conclusion ----------------------------------------
    provenance = []
    if accusation is not None:
        accuser = state.agents[accusation["by"]]
        for evidence_id in accusation["cited"]:
            holding = accuser.holdings.get(evidence_id)
            first = state.discovered.get(evidence_id)
            provenance.append({
                "id": evidence_id,
                "title": scenario.evidence[evidence_id].title,
                "kind": scenario.evidence[evidence_id].kind,
                "key": evidence_id in key,
                "first_found_by": first.by if first else None,
                "first_found_tick": first.tick if first else None,
                "reached_accuser_tick": holding.tick if holding else None,
                "chain": holding.chain if holding else [],
            })

    return {
        "outcome": outcome,
        "category": category,
        "culprit": truth.culprit,
        "accused": accusation["suspect"] if accusation else None,
        "accusation_tick": accusation["tick"] if accusation else None,
        "accusation_supported": supported,
        "close_reason": state.close_reason,
        "lead": lead,
        "solution": truth.solution,
        "evidence": evidence,
        "key_facts": key_facts,
        "claims": claims,
        "contradictions": contradictions,
        "agents": agents,
        "effort": effort,
        "deception": deception,
        "testimony": testimony,
        "provenance": provenance,
    }


def summary_row(scenario: Scenario, state: SimState, events: list[Event]) -> dict[str, Any]:
    """One flat row per run, for sweeps and run comparison."""
    result = evaluate(scenario, state, events)
    return {
        "seed": state.seed,
        "outcome": result["outcome"],
        "category": result["category"],
        "accused": result["accused"],
        "supported": result["accusation_supported"],
        "ticks": result["effort"]["ticks"],
        "actions": result["effort"]["actions"],
        "key_evidence": f'{result["evidence"]["key_discovered"]["num"]}/{result["evidence"]["key_discovered"]["den"]}',
        "all_evidence": f'{result["evidence"]["all_discovered"]["num"]}/{result["evidence"]["all_discovered"]["den"]}',
        "claims": result["claims"]["published_by_agents"],
        "false_claims": result["claims"]["false"]["num"],
        "false_retracted": result["claims"]["false_retracted"]["num"],
        "unsupported_guilt_claims": result["claims"]["unsupported_guilt"]["num"],
        "withheld_answers": result["deception"]["answers_with_withholding"],
        "withholding_noticed": result["deception"]["noticed"]["num"],
        "escalations": len(result["deception"]["escalations"]),
        "statements": result["testimony"]["statements"],
        "false_statements": result["testimony"]["false"]["num"],
        "false_ever_accepted": result["testimony"]["false_ever_accepted"]["num"],
        "false_accepted_at_close": result["testimony"]["false_accepted_at_close"]["num"],
        "false_speakers_impeached": f'{result["testimony"]["false_speakers_impeached"]["num"]}/{result["testimony"]["false_speakers_impeached"]["den"]}',
        "head_hash": state.head_hash[:12],
    }
