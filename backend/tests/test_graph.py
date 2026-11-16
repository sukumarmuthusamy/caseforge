"""The knowledge graph is a faithful, provenance-carrying projection of state."""

from __future__ import annotations

import pytest

from caseforge.__main__ import run_investigation
from caseforge.graph import project_graph
from caseforge.state import fold

NODE_TYPES = {"person", "location", "object", "evidence", "proposition", "claim", "statement"}
EDGE_TYPES = {
    "observed", "received", "communicated_to", "reported", "supports", "contradicts",
    "cites", "associated_with", "located_at", "suspects", "accused", "distrusts",
    "addressed", "relays", "witnessed", "doubts",
}


def index(graph):
    return {n["id"]: n for n in graph["nodes"]}, {e["id"]: e for e in graph["edges"]}


def test_graph_is_well_formed_and_within_the_ontology(scenario, solved):
    graph = project_graph(scenario, solved.state)
    nodes, edges = index(graph)
    assert len(nodes) == len(graph["nodes"]) and len(edges) == len(graph["edges"])
    assert {n["type"] for n in nodes.values()} <= NODE_TYPES
    assert {e["type"] for e in edges.values()} <= EDGE_TYPES
    for edge in edges.values():
        assert edge["source"] in nodes and edge["target"] in nodes, edge
        assert isinstance(edge["seq"], int) and isinstance(edge["tick"], int)
        assert 0 <= edge["seq"] <= solved.state.seq


def test_evidence_nodes_match_discoveries(scenario, solved):
    nodes, _ = index(project_graph(scenario, solved.state))
    evidence = {n["ref"]: n for n in nodes.values() if n["type"] == "evidence"}
    assert set(evidence) == set(solved.state.discovered)
    for evidence_id, node in evidence.items():
        assert node["first_tick"] == solved.state.discovered[evidence_id].tick
        assert node["holders"] == sorted(a for a, s in solved.state.agents.items() if evidence_id in s.holdings)


def test_shared_evidence_keeps_its_source_and_chain_of_custody(scenario, solved):
    _, edges = index(project_graph(scenario, solved.state))
    received = [e for e in edges.values() if e["type"] == "received"]
    assert received
    for edge in received:
        agent = edge["source"].removeprefix("ent:")
        evidence_id = edge["target"].removeprefix("ev:")
        holding = solved.state.agents[agent].holdings[evidence_id]
        assert edge["sender"] == holding.from_agent and edge["chain"] == holding.chain
        assert edge["chain"][-1] == agent and len(edge["chain"]) >= 2
        # The chain starts with whoever actually obtained the record first-hand.
        origin = solved.state.agents[edge["chain"][0]].holdings[evidence_id]
        assert origin.via in ("inspect", "initial", "released")
        assert f"communicated_to:ent:{holding.from_agent}>ent:{agent}" in edges


def test_observed_edges_are_first_hand_only(scenario, solved):
    _, edges = index(project_graph(scenario, solved.state))
    for edge in (e for e in edges.values() if e["type"] == "observed"):
        agent = edge["source"].removeprefix("ent:")
        holding = solved.state.agents[agent].holdings[edge["target"].removeprefix("ev:")]
        assert holding.via != "shared" and edge["seq"] == holding.seq


def test_a_statement_is_attributed_to_its_speaker_not_promoted_to_fact(scenario, solved):
    nodes, edges = index(project_graph(scenario, solved.state))
    # The cleaner's statement is linked to the cleaner.
    assert "reported:ent:alvarez>ev:E04" in edges
    # The proposition it asserts carries belief status per agent and no truth flag.
    prop = nodes["prop:at(mercer,east_corridor,oct14_2145)"]
    assert "truth" not in prop
    assert prop["statuses"]["okafor"] == "rejected"
    support = edges["supports:ev:E04>prop:at(mercer,east_corridor,oct14_2145)"]
    assert support["kind"] == "testimony"


def test_published_claim_and_rumor_keep_their_origin(scenario):
    engine = run_investigation(scenario, 7, {}, [(0, "rumor_contractor")])
    nodes, edges = index(project_graph(scenario, engine.state))
    claims = [n for n in nodes.values() if n["type"] == "claim"]
    by = {n["by"] for n in claims}
    assert "anonymous" in by and "nair" in by
    for claim in claims:
        authored = [e for e in edges.values() if e["type"] == "reported" and e["target"] == claim["id"]]
        if claim["by"] == "anonymous":
            assert authored == [] and claim["label"].startswith("Rumor:")
        else:
            assert [e["source"] for e in authored] == [f"ent:{claim['by']}"]
        alleges = [e for e in edges.values() if e["type"] == "supports" and e["source"] == claim["id"]]
        assert len(alleges) == 1 and alleges[0]["kind"] == "hearsay"


def test_recognized_contradictions_appear_as_edges(scenario, solved):
    _, edges = index(project_graph(scenario, solved.state))
    pairs = {e["id"].removeprefix("contradicts:") for e in edges.values() if e["type"] == "contradicts"}
    expected = {pair for agent in solved.state.agents.values() for pair in agent.contradictions}
    assert pairs and pairs <= expected


def test_agent_perspective_shows_only_what_that_agent_holds(scenario, solved):
    for agent_id, agent in solved.state.agents.items():
        nodes, edges = index(project_graph(scenario, solved.state, agent_id))
        assert {n["ref"] for n in nodes.values() if n["type"] == "evidence"} == set(agent.holdings)
        visible_claims = {n["ref"] for n in nodes.values() if n["type"] == "claim"}
        assert visible_claims == {c.id for c in solved.state.claims.values() if c.by == agent_id or c.id in agent.heard}
        for node in (n for n in nodes.values() if n["type"] == "proposition"):
            assert set(node["statuses"]) <= {agent_id}
            assert node.get("status") == (agent.beliefs[node["ref"]].status if node["ref"] in agent.beliefs else None)
        holders = {e["source"] for e in edges.values() if e["type"] in ("observed", "received")}
        assert holders <= {f"ent:{agent_id}"}


def test_unknown_perspective_is_an_error(scenario, solved):
    with pytest.raises(KeyError):
        project_graph(scenario, solved.state, "voss")


def test_hidden_entities_appear_only_once_mentioned(scenario, solved):
    start = fold([e for e in solved.events if e.tick == 0])
    nodes, _ = index(project_graph(scenario, start))
    assert "ent:card0417" not in nodes and "ent:badge_desk" not in nodes
    assert "ent:osteria" in nodes  # Brandt's receipt is on the table from the start
    nodes, _ = index(project_graph(scenario, start, "okafor"))
    assert "ent:osteria" not in nodes  # but the detective has not seen it
    nodes, _ = index(project_graph(scenario, solved.state))
    assert nodes["ent:card0417"]["first_tick"] == solved.state.discovered["E01"].tick


def test_graph_only_grows_evidence_over_time(scenario, solved):
    previous: set[str] = set()
    for tick in range(0, solved.state.tick + 1):
        state = fold([e for e in solved.events if e.tick <= tick])
        nodes, _ = index(project_graph(scenario, state))
        current = {n["id"] for n in nodes.values() if n["type"] in ("evidence", "claim", "person", "location", "object")}
        assert previous <= current
        assert all(n["first_tick"] <= tick for n in nodes.values())
        previous = current


def test_projection_is_deterministic(scenario, solved):
    assert project_graph(scenario, solved.state) == project_graph(scenario, fold(solved.events))


def at_tick(scenario, solved, tick):
    from caseforge.engine import Engine

    return Engine(scenario, [e for e in solved.events if e.tick <= tick])


def test_provenance_does_not_move_when_an_unrelated_event_arrives(scenario, solved):
    """A policy change must not re-date any relationship."""
    engine = at_tick(scenario, solved, 6)
    for perspective in ("all", *scenario.agent_ids):
        before = project_graph(scenario, engine.state, perspective)
        probe = at_tick(scenario, solved, 6)
        probe.set_policy("nair", "hasty")
        assert probe.events[-1].type == "PolicyChanged"
        after = project_graph(scenario, probe.state, perspective)
        assert after["nodes"] == before["nodes"] and after["edges"] == before["edges"], perspective
        assert after["seq"] == before["seq"] + 1  # only the header knows the log grew


def test_reasoning_edges_point_at_the_event_that_explains_them(scenario, solved):
    """Every derivation, suspicion and contradiction edge names an event that actually caused it."""
    by_seq = {e.seq: e for e in solved.events}
    checked = {"derivation": 0, "suspects": 0, "contradicts": 0, "derived_node": 0}
    for tick in (4, 6, 9, solved.state.tick):
        state = fold([e for e in solved.events if e.tick <= tick])
        for perspective in ("all", *scenario.agent_ids):
            graph = project_graph(scenario, state, perspective)
            nodes, edges = index(graph)
            for edge in edges.values():
                if "rule" in edge:
                    target = edge["target"].removeprefix("prop:")
                    for agent_id, entry in edge["agents"].items():
                        for seq in (entry["seq"], entry["changed_seq"]):
                            cause = by_seq[seq]
                            assert cause.type == "BeliefsRevised" and cause.data["agent"] == agent_id
                            assert target in cause.data["changes"], (edge["id"], seq)
                        introduced = by_seq[entry["seq"]].data["changes"][target]
                        assert any(d["rule"] == edge["rule"] for d in introduced["derivations"])
                    assert edge["seq"] == min(a["seq"] for a in edge["agents"].values())
                    checked["derivation"] += 1
                elif edge["type"] == "suspects":
                    agent_id, suspect = edge["source"].removeprefix("ent:"), edge["target"].removeprefix("ent:")
                    cause = by_seq[edge["seq"]]
                    assert cause.type == "BeliefsRevised" and cause.data["agent"] == agent_id
                    assert cause.data["prime_after"] == suspect and cause.data["prime_before"] != suspect
                    latest = by_seq[edge["changed_seq"]]
                    assert latest.type == "BeliefsRevised" and latest.data["agent"] == agent_id
                    checked["suspects"] += 1
                elif edge["type"] == "contradicts":
                    pair = set(edge["id"].removeprefix("contradicts:").split("|"))
                    for agent_id, entry in edge["agents"].items():
                        cause = by_seq[entry["seq"]]
                        assert cause.type == "ContradictionRecognized" and cause.data["agent"] == agent_id
                        assert {cause.data["a"], cause.data["b"]} == pair
                    assert edge["seq"] == min(a["seq"] for a in edge["agents"].values())
                    checked["contradicts"] += 1
            evidenced = {e["target"] for e in edges.values() if e["type"] == "supports" and "rule" not in e}
            for node in nodes.values():
                if node["type"] == "proposition" and node["id"] not in evidenced:
                    cause = by_seq[node["first_seq"]]  # known only by inference
                    assert cause.type == "BeliefsRevised" and cause.data["changes"][node["ref"]] is not None
                    assert node["first_tick"] == cause.tick
                    checked["derived_node"] += 1
    assert all(checked.values()), checked


def test_combined_graph_keeps_each_agents_view_of_a_derivation(scenario, solved):
    """When agents disagree about a derivation, the combined edge says so and keeps every side."""
    state = fold([e for e in solved.events if e.tick <= 6])
    _, combined = index(project_graph(scenario, state))
    per_agent = {a: index(project_graph(scenario, state, a))[1] for a in scenario.agent_ids}
    mixed = 0
    for edge_id, edge in combined.items():
        if "rule" not in edge:
            continue
        expected = {a: edges[edge_id]["active"] for a, edges in per_agent.items() if edge_id in edges}
        assert {a: entry["active"] for a, entry in edge["agents"].items()} == expected
        if len(set(expected.values())) > 1:
            mixed += 1
            assert edge["state"] == "mixed" and edge["active"] is None
        else:
            assert edge["state"] == ("active" if next(iter(expected.values())) else "defeated")
            assert edge["active"] is next(iter(expected.values()))
        for agent_id, entry in edge["agents"].items():
            mine = per_agent[agent_id][edge_id]
            assert (mine["seq"], mine["changed_seq"]) == (entry["seq"], entry["changed_seq"])
            assert mine["state"] in ("active", "defeated")  # one agent never disagrees with itself
    assert mixed >= 1, "seed 7 at tick 6 has agents on both sides of the card-holder inference"
    r1 = combined["supports:R1:prop:card_holder(card0417,brandt)>prop:at(brandt,lab3,oct14_2145)"]
    assert r1["agents"]["okafor"]["active"] is False and r1["agents"]["okafor"]["defeated_by"] == "card_cloned(card0417)"
    assert r1["agents"]["brandt"]["active"] is True and r1["agents"]["reyes"]["active"] is True


def test_a_defeated_derivation_keeps_its_origin_and_records_the_defeat(scenario, solved):
    final = solved.state.agents["okafor"]
    stamp = final.derivation_stamps["at(brandt,lab3,oct14_2145)"]["R1|card_holder(card0417,brandt)"]
    by_seq = {e.seq: e for e in solved.events}
    assert stamp.first.seq < stamp.last.seq
    introduced = by_seq[stamp.first.seq].data["changes"]["at(brandt,lab3,oct14_2145)"]["derivations"]
    defeated = by_seq[stamp.last.seq].data["changes"]["at(brandt,lab3,oct14_2145)"]["derivations"]
    assert [d["active"] for d in introduced] == [True] and [d["active"] for d in defeated] == [False]


def test_final_graph_records_the_accusation_and_suspicion(scenario, solved):
    _, edges = index(project_graph(scenario, solved.state))
    assert edges["accused:ent:okafor>ent:whitlock"]["seq"] == solved.state.accusation["seq"]
    assert edges["suspects:ent:okafor>ent:whitlock"]["score"] == solved.state.agents["okafor"].suspects["whitlock"].score
    assert edges["located_at:ent:aurora>ent:lab3"]["seq"] == 0
