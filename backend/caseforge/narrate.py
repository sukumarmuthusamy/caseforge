"""One-line, factual descriptions of events for timelines and the CLI.

Narration only restates what an event's payload already contains, using names
from the scenario's public part and titles of evidence the event itself
delivered. It adds no information.
"""

from __future__ import annotations

from .models import Event, Proposition
from .scenario import ANONYMOUS, Scenario


def _name(scenario: Scenario, entity_id: str) -> str:
    if entity_id == ANONYMOUS:
        return "An anonymous source"
    if entity_id == "user":
        return "The operator"
    entity = scenario.entities.get(entity_id)
    return entity.name if entity else entity_id


def _slot(scenario: Scenario, slot_id: str) -> str:
    return scenario.slots.get(slot_id, slot_id)


def describe_proposition(scenario: Scenario, key: str) -> str:
    """Readable form of a proposition key."""
    try:
        prop = Proposition.parse(key)
    except ValueError:
        return key
    a = prop.args
    n = lambda i: _name(scenario, a[i])  # noqa: E731
    templates = {
        "at": lambda: f"{n(0)} was at {n(1)} ({_slot(scenario, a[2])})",
        "crime_at": lambda: f"The theft happened at {n(0)} ({_slot(scenario, a[1])})",
        "card_used": lambda: f"{n(0)} was used at {n(1)} ({_slot(scenario, a[2])})",
        "card_holder": lambda: f"{n(0)} is registered to {n(1)}",
        "card_cloned": lambda: f"{n(0)} was cloned",
        "card_written": lambda: f"A copy of {n(0)} was written at {n(1)} ({_slot(scenario, a[2])})",
        "has_motive": lambda: f"{n(0)} had a motive",
        "took": lambda: f"{n(0)} took the {n(1)}",
        "could_use": lambda: f"{n(0)} could use a copy of {n(1)}",
        "crime_used": lambda: f"{n(0)} was used in the theft",
        "had": lambda: f"{n(0)} had {n(1)} ({_slot(scenario, a[2])})",
    }
    return templates[prop.predicate]()


def _source(scenario: Scenario, source_id: str | None) -> str:
    if source_id is None:
        return "what they know"
    source = scenario.sources.get(source_id)
    return source.name if source else source_id


def _titles(scenario: Scenario, ids) -> str:
    return ", ".join(f"{scenario.evidence[i].title} [{i}]" for i in ids) or "nothing"


def narrate(scenario: Scenario, event: Event) -> str:
    d = event.data
    t = event.type
    who = lambda key: _name(scenario, d[key])  # noqa: E731

    if t == "RunStarted":
        return f"Investigation opened (seed {d['seed']}, scenario {d['scenario_id']} v{d['scenario_version']})."
    if t == "TickStarted":
        return f"Tick {event.tick} begins. Turn order: {', '.join(_name(scenario, a) for a in d['order'])}."
    if t in ("ActionTaken", "ActionRejected"):
        action = d["action"]
        kind = action["type"]
        subject = who("agent")
        if kind == "inspect":
            text = f"{subject} searches {_source(scenario, action['source'])} for {_name(scenario, action['topic'])}"
        elif kind == "request":
            target = _name(scenario, action["to"])
            if action.get("source"):
                text = f"{subject} asks {target} to search {_source(scenario, action['source'])} for {_name(scenario, action['topic'])}"
            else:
                text = f"{subject} asks {target} about {_name(scenario, action['topic'])}"
        elif kind == "respond":
            text = f"{subject} {'answers' if action['accept'] else 'declines'} request {action['request_id']}"
            if action.get("withhold_about"):
                text += f", keeping back anything about {', '.join(_name(scenario, e) for e in action['withhold_about'])}"
        elif kind == "share":
            text = f"{subject} shares {action['evidence_id']} with {_name(scenario, action['to'])}"
        elif kind == "publish":
            text = f"{subject} publishes: {describe_proposition(scenario, action['proposition'])}"
        elif kind == "retract":
            text = f"{subject} retracts claim {action['claim_id']}"
        elif kind == "accuse":
            text = f"{subject} accuses {_name(scenario, action['suspect'])}"
        elif kind == "escalate":
            text = f"{subject} goes over {_name(scenario, action['against'])}'s head for direct access to the sources they operate"
        elif kind == "tell":
            said = describe_proposition(scenario, action["proposition"])
            if action.get("heard_from"):
                text = f"{subject} tells {_name(scenario, action['to'])} that {_name(scenario, action['heard_from'])} said: {said}"
            else:
                text = f"{subject} tells {_name(scenario, action['to'])}: {said}"
        else:
            text = f"{subject} waits"
        if t == "ActionRejected":
            return f"{text}. REJECTED ({d['code']}): {d['message']}"
        return text + "."
    if t == "SourceInspected":
        behalf = f" for {_name(scenario, d['on_behalf_of'])}" if d.get("on_behalf_of") else ""
        if not d["found"]:
            return f"{_source(scenario, d['source'])} holds nothing on {_name(scenario, d['topic'])}{behalf}."
        fresh = "" if d["new"] else " (already known)"
        return f"{_source(scenario, d['source'])} yields {_titles(scenario, d['found'])}{behalf}{fresh}."
    if t == "EvidenceObserved":
        how = "starts with" if d["via"] == "initial" else "obtains"
        return f"{who('agent')} {how} {_titles(scenario, [d['evidence']])}."
    if t == "EvidenceShared":
        return f"{who('sender')} gives {who('recipient')} {_titles(scenario, [d['evidence']])}."
    if t == "EvidenceReleased":
        return f"{who('recipient')} receives {_titles(scenario, [d['evidence']])} through an intervention."
    if t == "RequestSent":
        return f"Request {d['request']}: {who('sender')} to {who('recipient')}, {_source(scenario, d.get('source'))} on {_name(scenario, d['topic'])}."
    if t == "RequestAnswered":
        outcome = {"fulfilled": "fulfilled", "nothing_found": "nothing found", "declined": "declined"}[d["outcome"]]
        return f"Request {d['request']} {outcome} by {who('by')}."
    if t == "EvidenceWithheld":
        return f"{who('by')} holds back {_titles(scenario, d['evidence'])} from {who('requester')} (request {d['request']})."
    if t == "DiscrepancyNoticed":
        return f"{who('agent')} notices that {who('against')}'s answer to request {d['request']} left out {_titles(scenario, [d['evidence']])}."
    if t == "AccessEscalated":
        return f"{who('agent')} takes direct access to {_source(scenario, d['source'])}, bypassing {who('against')}."
    if t == "ClaimPublished":
        return f"{who('by')} claims publicly: {describe_proposition(scenario, d['proposition'])}. [{d['claim']}]"
    if t == "ClaimRetracted":
        return f"{who('by')} retracts claim {d['claim']}."
    if t == "BeliefsRevised":
        changes = len(d["changes"])
        prime = ""
        if d["prime_before"] != d["prime_after"]:
            before = _name(scenario, d["prime_before"]) if d["prime_before"] else "nobody"
            after = _name(scenario, d["prime_after"]) if d["prime_after"] else "nobody"
            prime = f" Prime suspect: {before} -> {after}."
        return f"{who('agent')} revises {changes} belief{'s' if changes != 1 else ''} because of {', '.join(d['because']) or 'nothing new'}.{prime}"
    if t == "ContradictionRecognized":
        return f"{who('agent')} sees a contradiction: \"{describe_proposition(scenario, d['a'])}\" versus \"{describe_proposition(scenario, d['b'])}\"."
    if t == "StatementMade":
        said = describe_proposition(scenario, d["proposition"])
        basis = {
            "observed": "saw it",
            "held": f"holds {', '.join(d['backing'])}",
            "heard": f"was told so by {_name(scenario, d['origin'])}" if d.get("origin") else "was told so",
            "none": "has nothing for it",
        }[d["grounds"]]
        return f"Statement {d['statement']}: {who('speaker')} to {who('recipient')}, \"{said}\". The speaker {basis}."
    if t == "StatementWeighed":
        verb = {"accepted": "accepts", "rejected": "rejects", "questioned": "does not settle on"}[d["stance"]]
        return f"{who('agent')} {verb} statement {d['statement']} (belief: {d['belief']})."
    if t == "CredibilityRevised":
        speaker = _name(scenario, d["speaker"])
        c = d["credibility"]
        if c is None:
            return f"{who('agent')} no longer has anything to check {speaker}'s word against."
        if c["standing"] == "impeached":
            caught = "; ".join(describe_proposition(scenario, key) for key in c["refuted"])
            return f"{who('agent')} has caught {speaker} out: evidence contradicts \"{caught}\"."
        return f"{who('agent')} finds {speaker}'s word borne out by evidence ({len(c['corroborated'])} statement{'s' if len(c['corroborated']) != 1 else ''})."
    if t == "InterventionApplied":
        spec = scenario.interventions.get(d["intervention"])
        return f"Intervention: {spec.label if spec else d['intervention']}."
    if t == "AccessGranted":
        return f"{who('agent')} is granted direct access to {_source(scenario, d['source'])}."
    if t == "PolicyChanged":
        return f"{who('agent')} now follows the {d['policy']} policy."
    if t == "AccusationMade":
        return f"{who('by')} formally accuses {_name(scenario, d['suspect'])}, citing {', '.join(d['cited']) or 'no evidence'}."
    if t == "CaseClosed":
        return "Case closed: " + ("an accusation was made." if d["reason"] == "accusation" else "the tick limit was reached without an accusation.")
    return t
