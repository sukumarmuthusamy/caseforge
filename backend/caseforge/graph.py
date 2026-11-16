"""Knowledge-graph projection.

The graph is computed from simulation state on request; nothing is stored.

Ontology
--------
Nodes
    person, location, object   entities of the scenario (a card or a tool is an object)
    evidence                   a discovered evidence record
    proposition                a structured statement some evidence or claim asserts
    claim                      a public statement by an agent or an anonymous rumor
    statement                  something one agent told another on its own word, or passed on

Edges. Each carries `seq` and `tick` of the event that created it. Edges that
come from reasoning (derivations, suspicion, contradictions) also carry
`changed_seq` / `changed_tick`, the event that last changed them, and an
`agents` map with the same facts for each agent the edge belongs to, so the
combined view never has to pick one agent's reasoning over another's.
    observed          agent -> evidence       found first-hand or released to them
    received          agent -> evidence       handed over by another agent (`sender`)
    communicated_to   agent -> agent          at least one record passed between them
    reported          person -> evidence      the speaker of a statement
                      agent  -> claim         the author of a public claim
    supports          evidence -> proposition what a record asserts
                      claim -> proposition
                      proposition -> proposition   a derivation (`rule`); `state` is
                                                   active, defeated or mixed (agents differ)
    contradicts       proposition <-> proposition  mutually exclusive statements
    cites             claim -> evidence
    associated_with   proposition -> entity   what the statement is about
    located_at        object -> location      where the object was kept
    suspects          agent -> person         current prime suspect (`score`), since `seq`
    accused           agent -> person         the formal accusation
    distrusts         agent -> agent          the first agent caught the second leaving records
                                              out of an answer (`items`: the records)
    reported          agent -> statement      the speaker (`label`: told, or passed on)
    addressed         statement -> agent      who it was said to (`stance`: what they make of it)
    supports          statement -> proposition what was said
    relays            statement -> statement  a statement passing another one on
    witnessed         agent -> proposition    what the agent saw for itself
    doubts            agent -> person         the agent holds evidence against something that
                                              person said (`items`: the refuted statements)

A statement node says who spoke and what was said. It carries the recipient's
stance, and `grounds` (what the speaker had for it) only in the combined view
and the speaker's own: the recipient is not told.

A proposition node is never marked true. It carries belief status per agent,
which is the only sense in which the graph "knows" anything.
"""

from __future__ import annotations

from typing import Any

from .models import PREDICATES, Proposition
from .narrate import describe_proposition
from .reasoning import contradiction_key
from .scenario import ANONYMOUS, Scenario
from .state import SimState, derivation_key
from .views import observations_of

ALL = "all"


def _entity_type(kind: str) -> str:
    return "object" if kind in ("card", "tool") else kind


def project_graph(scenario: Scenario, state: SimState, perspective: str = ALL) -> dict[str, Any]:
    if perspective != ALL and perspective not in state.agents:
        raise KeyError(f"unknown perspective: {perspective}")
    viewers = sorted(state.agents) if perspective == ALL else [perspective]

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}

    def add_edge(source: str, target: str, edge_type: str, seq: int, tick: int, **attrs: Any) -> None:
        edge_id = f"{edge_type}:{source}>{target}"
        if edge_id in edges:
            if seq < edges[edge_id]["seq"]:
                edges[edge_id].update({"seq": seq, "tick": tick})
            return
        edges[edge_id] = {"id": edge_id, "source": source, "target": target, "type": edge_type, "seq": seq, "tick": tick, **attrs}

    # Visible evidence: when it first became visible in this perspective, and to whom.
    visible: dict[str, dict[str, Any]] = {}
    for agent_id in viewers:
        for evidence_id, holding in state.agents[agent_id].holdings.items():
            entry = visible.setdefault(evidence_id, {"seq": holding.seq, "tick": holding.tick, "holders": []})
            entry["holders"].append(agent_id)
            if holding.seq < entry["seq"]:
                entry.update({"seq": holding.seq, "tick": holding.tick})

    visible_claims = [
        claim for claim in sorted(state.claims.values(), key=lambda c: c.seq)
        if perspective == ALL or claim.by == perspective or claim.id in state.agents[perspective].heard
    ]

    # Entities: public ones are there from the start; hidden ones appear when first mentioned.
    first_mention: dict[str, tuple[int, int]] = {e: (0, 0) for e in scenario.public_entity_ids}

    def mention(entity_id: str, seq: int, tick: int) -> None:
        if entity_id in scenario.entities and (entity_id not in first_mention or seq < first_mention[entity_id][0]):
            first_mention[entity_id] = (seq, tick)

    for evidence_id, entry in visible.items():
        spec = scenario.evidence[evidence_id]
        for entity_id in spec.mentions:
            mention(entity_id, entry["seq"], entry["tick"])
        for prop in spec.asserts:
            for arg, kind in zip(prop.args, PREDICATES[prop.predicate]):
                if kind != "slot":
                    mention(arg, entry["seq"], entry["tick"])
    for claim in visible_claims:
        for arg in Proposition.parse(claim.proposition).args:
            mention(arg, claim.seq, claim.tick)
    visible_statements = [
        s for s in sorted(state.statements.values(), key=lambda s: s.seq)
        if perspective == ALL or perspective in (s.speaker, s.recipient)
    ]
    for statement in visible_statements:
        for arg in Proposition.parse(statement.proposition).args:
            mention(arg, statement.seq, statement.tick)
    witnessed = {agent_id: observations_of(scenario, agent_id) for agent_id in viewers}
    for seen in witnessed.values():
        for prop in seen:
            for arg in prop.args:
                mention(arg, 0, 0)

    for entity_id, (seq, tick) in sorted(first_mention.items()):
        entity = scenario.entities[entity_id]
        agent_spec = scenario.agents.get(entity_id)
        nodes[f"ent:{entity_id}"] = {
            "id": f"ent:{entity_id}",
            "type": _entity_type(entity.kind),
            "label": entity.name,
            "ref": entity_id,
            "description": entity.description,
            "agent": agent_spec is not None,
            "role": agent_spec.role if agent_spec else None,
            "suspect": entity_id in scenario.case.suspects,
            "first_seq": seq,
            "first_tick": tick,
        }
    add_edge(f"ent:{scenario.case.object}", f"ent:{scenario.case.crime_location}", "located_at", 0, 0, label="kept in")

    # Propositions.
    prop_first: dict[str, tuple[int, int]] = {}

    def touch_prop(key: str, seq: int, tick: int) -> None:
        if key not in prop_first or seq < prop_first[key][0]:
            prop_first[key] = (seq, tick)

    for evidence_id, entry in sorted(visible.items()):
        spec = scenario.evidence[evidence_id]
        nodes[f"ev:{evidence_id}"] = {
            "id": f"ev:{evidence_id}",
            "type": "evidence",
            "label": spec.title,
            "ref": evidence_id,
            "kind": spec.kind,
            "speaker": spec.speaker,
            "holders": sorted(entry["holders"]),
            "first_seq": entry["seq"],
            "first_tick": entry["tick"],
        }
        if spec.speaker and spec.speaker in first_mention:
            add_edge(f"ent:{spec.speaker}", f"ev:{evidence_id}", "reported", entry["seq"], entry["tick"], label="said")
        for prop in spec.asserts:
            touch_prop(prop.key, entry["seq"], entry["tick"])
            add_edge(f"ev:{evidence_id}", f"prop:{prop.key}", "supports", entry["seq"], entry["tick"], label="asserts", kind=spec.kind)

    for claim in visible_claims:
        nodes[f"claim:{claim.id}"] = {
            "id": f"claim:{claim.id}",
            "type": "claim",
            "label": ("Rumor: " if claim.by == ANONYMOUS else "Claim: ") + describe_proposition(scenario, claim.proposition),
            "ref": claim.id,
            "by": claim.by,
            "status": claim.status,
            "text": claim.text,
            "first_seq": claim.seq,
            "first_tick": claim.tick,
        }
        touch_prop(claim.proposition, claim.seq, claim.tick)
        add_edge(f"claim:{claim.id}", f"prop:{claim.proposition}", "supports", claim.seq, claim.tick, label="alleges", kind="hearsay", retracted=claim.status == "retracted")
        if claim.by in state.agents:
            add_edge(f"ent:{claim.by}", f"claim:{claim.id}", "reported", claim.seq, claim.tick, label="published")
        for evidence_id in claim.cited:
            if evidence_id in visible:
                add_edge(f"claim:{claim.id}", f"ev:{evidence_id}", "cites", claim.seq, claim.tick, label="cites")

    for statement in visible_statements:
        node_id = f"st:{statement.id}"
        passed_on = statement.origin is not None
        node = {
            "id": node_id,
            "type": "statement",
            "label": ("Passed on: " if passed_on else "Said: ") + describe_proposition(scenario, statement.proposition),
            "ref": statement.id,
            "by": statement.speaker,
            "to": statement.recipient,
            "origin": statement.origin,
            "first_seq": statement.seq,
            "first_tick": statement.tick,
        }
        if perspective in (ALL, statement.speaker):
            node["grounds"] = statement.grounds
        stance = statement.stances[-1] if statement.stances else None
        if perspective in (ALL, statement.recipient) and stance is not None:
            node["stance"] = stance.stance
        nodes[node_id] = node
        touch_prop(statement.proposition, statement.seq, statement.tick)
        add_edge(f"ent:{statement.speaker}", node_id, "reported", statement.seq, statement.tick, label="passed on" if passed_on else "told")
        add_edge(node_id, f"ent:{statement.recipient}", "addressed", statement.seq, statement.tick, label="to", **(
            {"stance": stance.stance, "changed_seq": stance.seq, "changed_tick": stance.tick}
            if "stance" in node else {}
        ))
        add_edge(node_id, f"prop:{statement.proposition}", "supports", statement.seq, statement.tick, label="states", kind="testimony")
        if statement.relays and any(s.id == statement.relays for s in visible_statements):
            add_edge(node_id, f"st:{statement.relays}", "relays", statement.seq, statement.tick, label="passes on")
    for agent_id, seen in sorted(witnessed.items()):
        for prop in seen:
            touch_prop(prop.key, 0, 0)
            add_edge(f"ent:{agent_id}", f"prop:{prop.key}", "witnessed", 0, 0, label="saw")

    # Belief status per viewer, derived propositions and derivation edges.
    # Provenance comes from the reducer's stamps: the BeliefsRevised event that brought
    # the belief or derivation in, never the state being projected.
    statuses: dict[str, dict[str, str]] = {}
    derived: dict[str, dict[str, Any]] = {}
    for agent_id in viewers:
        agent = state.agents[agent_id]
        for key, belief in agent.beliefs.items():
            statuses.setdefault(key, {})[agent_id] = belief.status
            stamps = agent.derivation_stamps.get(key, {})
            for derivation in belief.derivations:
                for premise in derivation.premises:
                    stamp = stamps[derivation_key(derivation.rule, premise)]
                    edge_id = f"supports:{derivation.rule}:prop:{premise}>prop:{key}"
                    edge = derived.setdefault(edge_id, {
                        "id": edge_id, "source": f"prop:{premise}", "target": f"prop:{key}", "type": "supports",
                        "label": derivation.rule, "rule": derivation.rule, "agents": {},
                    })
                    edge["agents"][agent_id] = {
                        "active": derivation.active,
                        "defeated_by": derivation.defeated_by,
                        "seq": stamp.first.seq, "tick": stamp.first.tick,
                        "changed_seq": stamp.last.seq, "changed_tick": stamp.last.tick,
                    }
    for edge in derived.values():
        per_agent = edge["agents"]
        first = min(per_agent.values(), key=lambda a: a["seq"])
        last = max(per_agent.values(), key=lambda a: a["changed_seq"])
        active = {a["active"] for a in per_agent.values()}
        edge.update({
            "seq": first["seq"], "tick": first["tick"],
            "changed_seq": last["changed_seq"], "changed_tick": last["changed_tick"],
            # One value only when every agent holding the derivation agrees.
            "state": "mixed" if len(active) > 1 else "active" if True in active else "defeated",
            "active": None if len(active) > 1 else True in active,
        })
        edges[edge["id"]] = edge
    for key in statuses:
        if key not in prop_first:
            # Known only through derivation: it exists since the first agent came to hold it.
            first = min((state.agents[a].belief_stamps[key].first for a in statuses[key]), key=lambda ref: ref.seq)
            prop_first[key] = (first.seq, first.tick)

    for key, (seq, tick) in sorted(prop_first.items()):
        prop = Proposition.parse(key)
        node: dict[str, Any] = {
            "id": f"prop:{key}",
            "type": "proposition",
            "label": describe_proposition(scenario, key),
            "ref": key,
            "predicate": prop.predicate,
            "statuses": statuses.get(key, {}),
            "first_seq": seq,
            "first_tick": tick,
        }
        if perspective != ALL:
            node["status"] = statuses.get(key, {}).get(perspective)
        nodes[node["id"]] = node
        for arg, kind in zip(prop.args, PREDICATES[prop.predicate]):
            if kind != "slot" and f"ent:{arg}" in nodes:
                add_edge(node["id"], f"ent:{arg}", "associated_with", seq, tick, label="about")

    # Drop derivation edges whose endpoints never materialised.
    for edge_id in [i for i, e in edges.items() if e["source"] not in nodes or e["target"] not in nodes]:
        del edges[edge_id]

    # Contradictions any viewer has recognized, dated by the event that recognized them.
    for agent_id in viewers:
        agent = state.agents[agent_id]
        for pair in agent.contradictions:
            a, b = pair.split("|")
            if f"prop:{a}" not in nodes or f"prop:{b}" not in nodes:
                continue
            ref = agent.contradiction_refs[pair]
            edge_id = f"contradicts:{contradiction_key(a, b)}"
            edge = edges.setdefault(edge_id, {
                "id": edge_id, "source": f"prop:{a}", "target": f"prop:{b}", "type": "contradicts",
                "seq": ref.seq, "tick": ref.tick, "label": "contradicts", "agents": {},
            })
            edge["agents"][agent_id] = {"seq": ref.seq, "tick": ref.tick}
            if ref.seq < edge["seq"]:
                edge.update({"seq": ref.seq, "tick": ref.tick})

    # Who holds what, and how it travelled.
    for agent_id in viewers:
        agent = state.agents[agent_id]
        for evidence_id, holding in agent.holdings.items():
            if holding.via == "shared":
                add_edge(f"ent:{agent_id}", f"ev:{evidence_id}", "received", holding.seq, holding.tick, label="received", sender=holding.from_agent, chain=holding.chain)
                if holding.from_agent:
                    pair_id = f"communicated_to:ent:{holding.from_agent}>ent:{agent_id}"
                    if pair_id in edges:
                        edges[pair_id]["items"].append(evidence_id)
                        if holding.seq < edges[pair_id]["seq"]:
                            edges[pair_id].update({"seq": holding.seq, "tick": holding.tick})
                    else:
                        edges[pair_id] = {
                            "id": pair_id, "source": f"ent:{holding.from_agent}", "target": f"ent:{agent_id}",
                            "type": "communicated_to", "seq": holding.seq, "tick": holding.tick, "label": "shared with", "items": [evidence_id],
                        }
            else:
                add_edge(f"ent:{agent_id}", f"ev:{evidence_id}", "observed", holding.seq, holding.tick, label=holding.via, via=holding.via, chain=holding.chain)
        if agent.prime_suspect and agent.prime_since and agent.revised:
            score = agent.suspects[agent.prime_suspect].score if agent.prime_suspect in agent.suspects else None
            add_edge(
                f"ent:{agent_id}", f"ent:{agent.prime_suspect}", "suspects", agent.prime_since.seq, agent.prime_since.tick,
                label="suspects", score=score, changed_seq=agent.revised.seq, changed_tick=agent.revised.tick,
            )

    for agent_id in viewers:
        for d in state.agents[agent_id].discrepancies:
            edge_id = f"distrusts:ent:{agent_id}>ent:{d.against}"
            if edge_id in edges:
                edges[edge_id]["items"].append(d.evidence)
                edges[edge_id].update({"changed_seq": d.seq, "changed_tick": d.tick})
            else:
                edges[edge_id] = {
                    "id": edge_id, "source": f"ent:{agent_id}", "target": f"ent:{d.against}", "type": "distrusts",
                    "seq": d.seq, "tick": d.tick, "changed_seq": d.seq, "changed_tick": d.tick,
                    "label": "caught withholding", "items": [d.evidence],
                }

    # Whose word each viewer has caught out, dated by the event that first did.
    for agent_id in viewers:
        for speaker, seen in state.agents[agent_id].credibility.items():
            if seen.current is None or seen.current.standing != "impeached" or f"ent:{speaker}" not in nodes:
                continue
            since = next(h for h in reversed(seen.history) if h.standing == "impeached")
            last = seen.history[-1]
            edge_id = f"doubts:ent:{agent_id}>ent:{speaker}"
            edges[edge_id] = {
                "id": edge_id, "source": f"ent:{agent_id}", "target": f"ent:{speaker}", "type": "doubts",
                "seq": since.seq, "tick": since.tick, "changed_seq": last.seq, "changed_tick": last.tick,
                "label": "caught out", "items": list(seen.current.refuted),
            }

    if state.accusation and (perspective == ALL or perspective == state.accusation["by"]):
        add_edge(f"ent:{state.accusation['by']}", f"ent:{state.accusation['suspect']}", "accused", state.accusation["seq"], state.accusation["tick"], label="accused")

    for edge in edges.values():
        if "items" in edge:
            edge["items"] = sorted(set(edge["items"]))

    return {
        "perspective": perspective,
        "tick": state.tick,
        "seq": state.seq,
        "nodes": sorted(nodes.values(), key=lambda n: n["id"]),
        "edges": sorted(edges.values(), key=lambda e: e["id"]),
    }
