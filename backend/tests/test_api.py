"""HTTP API: the full user flow, error handling, and leak checks on every read route."""

from __future__ import annotations

import pytest
from .conftest import LocalClient as TestClient

from caseforge.api import create_app

from .conftest import SCENARIO_ID, SEED


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "api.sqlite3"


@pytest.fixture()
def client(db):
    with TestClient(create_app(db)) as c:
        yield c


def new_run(client, **body):
    response = client.post("/api/runs", json={"scenario_id": SCENARIO_ID, "seed": SEED, **body})
    assert response.status_code == 201, response.text
    return response.json()


def test_scenario_listing_is_public_information_only(client, scenario):
    everything = client.get("/api/scenarios").json()
    assert [s["id"] for s in everything] == ["missing_prototype", "quiet_substitution"]
    listed = everything[0]
    assert listed["id"] == SCENARIO_ID and listed["evidence_total"] == len(scenario.evidence)
    assert {a["id"] for a in listed["agents"]} == set(scenario.agents)
    assert {i["id"] for i in listed["interventions"]} == set(scenario.interventions)
    assert set(listed["policies"]) == {"baseline", "hasty", "deceptive", "llm"}
    text = client.get("/api/scenarios").text
    assert scenario.truth.solution not in text and "culprit" not in text


def test_full_investigation_flow(client, scenario):
    run = new_run(client, label="flow")
    rid = run["id"]
    assert run["tick"] == 0 and run["status"] == "running" and run["label"] == "flow"

    stepped = client.post(f"/api/runs/{rid}/step", json={"ticks": 1}).json()
    assert stepped["run"]["tick"] == 1
    assert stepped["events"][0]["type"] == "TickStarted" and all(e["summary"] for e in stepped["events"])

    snapshot = client.get(f"/api/runs/{rid}/snapshot").json()
    assert snapshot["tick"] == 1 and snapshot["is_latest"] and len(snapshot["agents"]) == 4
    assert snapshot["evidence_total"] == 17 and 0 < len(snapshot["evidence"]) < 17

    evaluation = client.get(f"/api/runs/{rid}/evaluation").json()
    assert evaluation["available"] is False and "result" not in evaluation
    assert evaluation["progress"]["evidence_discovered"] == len(snapshot["evidence"])

    final = client.post(f"/api/runs/{rid}/step", json={"ticks": 100}).json()["run"]
    assert final["status"] == "closed" and final["accused"] == "whitlock"

    evaluation = client.get(f"/api/runs/{rid}/evaluation").json()
    assert evaluation["available"] is True and evaluation["result"]["outcome"] == "solved"
    assert evaluation["result"]["solution"] == scenario.truth.solution

    report = client.get(f"/api/runs/{rid}/verify").json()
    assert all(report[k]["ok"] for k in ("chain", "fold", "decisions", "policies"))
    assert report["stored_matches_memory"] is True and report["head_hash"] == final["head_hash"]

    events = client.get(f"/api/runs/{rid}/events").json()
    assert [e["seq"] for e in events] == list(range(final["seq"] + 1))
    assert client.get(f"/api/runs/{rid}/events", params={"after": final["seq"] - 2}).json() == events[-2:]
    assert [r["id"] for r in client.get("/api/runs").json()] == [rid]


def _read_routes(rid: str, agents) -> list[tuple[str, dict]]:
    routes = [
        ("/api/scenarios", {}),
        ("/api/runs", {}),
        (f"/api/runs/{rid}", {}),
        (f"/api/runs/{rid}/snapshot", {}),
        (f"/api/runs/{rid}/snapshot", {"tick": 1}),
        (f"/api/runs/{rid}/events", {}),
        (f"/api/runs/{rid}/graph", {}),
        (f"/api/runs/{rid}/graph", {"tick": 2}),
        (f"/api/runs/{rid}/evaluation", {}),
        (f"/api/runs/{rid}/verify", {}),
        ("/api/compare", {"a": rid, "b": rid}),
    ]
    routes += [(f"/api/runs/{rid}/graph", {"perspective": agent}) for agent in agents]
    return routes


# The laboratory's read routes. They are not about an open run, so the run-scoped checks below do not apply
# to them; their own canary (test_lab_api.py: test_ground_truth_is_withheld_until_asked_for, and the one
# here) looks for the same markers of scenario truth in every body.
LAB_READ_ROUTES = [("/api/lab", {})] + [(f"/api/lab/challenges/{name}", {}) for name in (
    "control", "custodian_hasty", "lie_survives", "curator_did_it", "two_records_disagree", "two_keyholders",
)]


def test_laboratory_read_routes_carry_no_scenario_truth_unless_revealed(client):
    from caseforge import lab

    manifest = lab.default_manifest()
    assert {c["id"] for c in manifest["challenges"]} >= {p.rsplit("/", 1)[-1] for p, _ in LAB_READ_ROUTES[1:]}
    for path, params in LAB_READ_ROUTES:
        response = client.get(path, params=params)
        assert response.status_code == 200, (path, response.text)
        body = response.text
        for forbidden in ('"culprit"', '"solution"', '"key_facts"', '"truth":', '"private"', '"hidden_entities"', '"agendas"', '"protects"', '"ground_truth"'):
            assert forbidden not in body, f"{path} exposes {forbidden}"
        for challenge in manifest["challenges"]:
            assert challenge["question"] not in body, path
        # Who the accuser distrusted would point at who lied: only a count is shown.
        assert '"impeached_by_accuser":' not in body, path


def test_no_read_route_leaks_hidden_truth_while_the_case_is_open(client, scenario):
    """Canary test: fetch every GET route of an open run and search the raw bodies."""
    rid = new_run(client)["id"]
    client.post(f"/api/runs/{rid}/step", json={"ticks": 3})
    client.post(f"/api/runs/{rid}/interventions", json={"intervention_id": "rumor_contractor"})
    state = client.app.state.service._engine(rid).state
    undiscovered = [spec for eid, spec in scenario.evidence.items() if eid not in state.discovered]
    assert len(undiscovered) >= 8, "the test needs a run that still has secrets"
    truth = scenario.truth

    for path, params in _read_routes(rid, scenario.agent_ids):
        response = client.get(path, params=params)
        assert response.status_code == 200, (path, response.text)
        body = response.text
        for spec in undiscovered:
            assert spec.text not in body, f"{path} leaks the text of {spec.id}"
            assert spec.title not in body, f"{path} leaks the title of {spec.id}"
        assert truth.solution not in body, path
        for forbidden in ('"culprit"', '"solution"', '"key_evidence"', '"key_facts"', '"truth":', '"private"', '"hidden_entities"'):
            assert forbidden not in body, f"{path} exposes {forbidden}"
        # Entities that only undiscovered evidence mentions stay unknown to the observer.
        for hidden in ("whitlock_home", "reyes_home", "Whitlock's flat"):
            assert hidden not in body, f"{path} reveals {hidden}"


def test_reveal_unlocks_evaluation_and_truth_overlay(client, scenario):
    rid = new_run(client)["id"]
    client.post(f"/api/runs/{rid}/step", json={"ticks": 4})
    graph = client.get(f"/api/runs/{rid}/graph").json()
    assert graph["truth_shown"] is False
    assert all("truth" not in n for n in graph["nodes"])

    assert client.post(f"/api/runs/{rid}/reveal").json()["revealed"] is True
    evaluation = client.get(f"/api/runs/{rid}/evaluation").json()
    assert evaluation["available"] is True and evaluation["result"]["culprit"] == scenario.truth.culprit
    assert evaluation["result"]["outcome"] == "unresolved"
    graph = client.get(f"/api/runs/{rid}/graph").json()
    props = [n for n in graph["nodes"] if n["type"] == "proposition"]
    assert graph["truth_shown"] and props and all("truth" in n for n in props)
    # Revealing is not part of the simulation: the run continues and the log is unchanged by it.
    assert client.post(f"/api/runs/{rid}/step", json={"ticks": 1}).status_code == 200


def test_intervention_changes_backend_state(client):
    rid = new_run(client)["id"]
    before = client.get(f"/api/runs/{rid}/snapshot").json()
    assert all(not i["applied"] for i in before["interventions"])
    nair_before = next(a for a in before["agents"] if a["id"] == "nair")
    assert nair_before["holdings"] == []

    response = client.post(f"/api/runs/{rid}/interventions", json={"intervention_id": "leak_door_log"})
    assert response.status_code == 200
    assert [e["type"] for e in response.json()["events"]][:2] == ["InterventionApplied", "EvidenceReleased"]

    after = client.get(f"/api/runs/{rid}/snapshot").json()
    nair = next(a for a in after["agents"] if a["id"] == "nair")
    assert [h["id"] for h in nair["holdings"]] == ["E01"] and nair["holdings"][0]["via"] == "released"
    assert nair["prime_suspect"] == "brandt"
    assert next(i for i in after["interventions"] if i["id"] == "leak_door_log")["applied"] is True
    assert "E01" in after["evidence"] and after["evidence"]["E01"]["holders"] == ["nair"]


def test_state_survives_a_server_restart(db):
    with TestClient(create_app(db)) as first:
        rid = new_run(first)["id"]
        head = first.post(f"/api/runs/{rid}/step", json={"ticks": 3}).json()["run"]["head_hash"]
    with TestClient(create_app(db)) as second:
        run = second.get(f"/api/runs/{rid}").json()
        assert run["tick"] == 3 and run["head_hash"] == head
        assert second.post(f"/api/runs/{rid}/step", json={"ticks": 1}).json()["run"]["tick"] == 4


def test_errors_are_reported_and_leave_the_run_untouched(client):
    rid = new_run(client)["id"]
    seq = client.get(f"/api/runs/{rid}").json()["seq"]

    assert client.get("/api/runs/missing").status_code == 404
    assert client.get("/api/runs/missing/snapshot").status_code == 404
    assert client.post("/api/runs/missing/step", json={"ticks": 1}).status_code == 404
    assert client.post("/api/runs", json={"scenario_id": "atlantis"}).status_code == 404
    assert client.post("/api/runs", json={"scenario_id": SCENARIO_ID, "policies": {"okafor": "psychic"}}).status_code == 409
    assert client.post("/api/runs", json={"scenario_id": SCENARIO_ID, "policies": {"okafor": "llm"}}).status_code == 409
    assert client.post("/api/runs", json={"scenario_id": SCENARIO_ID, "policies": {"sherlock": "baseline"}}).status_code == 409
    assert client.post("/api/runs", json={"scenario_id": SCENARIO_ID, "seed": -1}).status_code == 422
    assert client.post(f"/api/runs/{rid}/step", json={"ticks": 0}).status_code == 422
    assert client.post(f"/api/runs/{rid}/step", json={"ticks": 5000}).status_code == 422
    assert client.post(f"/api/runs/{rid}/interventions", json={"intervention_id": "nope"}).status_code == 409
    assert client.post(f"/api/runs/{rid}/interventions", json={}).status_code == 422
    assert client.post(f"/api/runs/{rid}/policy", json={"agent": "okafor", "policy": "psychic"}).status_code == 409
    assert client.post(f"/api/runs/{rid}/policy", json={"agent": "sherlock", "policy": "hasty"}).status_code == 409
    assert client.post(f"/api/runs/{rid}/branch", json={"tick": 99}).status_code == 409
    assert client.get(f"/api/runs/{rid}/graph", params={"perspective": "voss"}).status_code == 404
    assert client.get(f"/api/runs/{rid}/snapshot", params={"tick": -1}).status_code == 422
    assert client.get("/api/nothing-here").status_code == 404

    assert client.get(f"/api/runs/{rid}").json()["seq"] == seq
    assert len(client.get("/api/runs").json()) == 1

    client.post(f"/api/runs/{rid}/step", json={"ticks": 100})
    closed = client.get(f"/api/runs/{rid}").json()
    assert client.post(f"/api/runs/{rid}/step", json={"ticks": 1}).status_code == 409
    assert client.post(f"/api/runs/{rid}/interventions", json={"intervention_id": "leak_door_log"}).status_code == 409
    assert client.get(f"/api/runs/{rid}").json()["seq"] == closed["seq"]


def test_policy_change_is_an_event_and_changes_behaviour(client):
    rid = new_run(client, seed=4)["id"]
    response = client.post(f"/api/runs/{rid}/policy", json={"agent": "okafor", "policy": "hasty"})
    assert [e["type"] for e in response.json()["events"]] == ["PolicyChanged"]
    assert response.json()["run"]["policies"]["okafor"] == "hasty"
    final = client.post(f"/api/runs/{rid}/step", json={"ticks": 100}).json()["run"]
    assert final["accused"] == "brandt"
    report = client.get(f"/api/runs/{rid}/verify").json()
    assert report["decisions"]["ok"] and report["policies"]["ok"]


def test_branch_and_compare_over_http(client):
    rid = new_run(client)["id"]
    client.post(f"/api/runs/{rid}/step", json={"ticks": 100})
    branch = client.post(f"/api/runs/{rid}/branch", json={"tick": 3, "label": "what if"})
    assert branch.status_code == 201
    bid = branch.json()["id"]
    assert branch.json()["tick"] == 3 and branch.json()["label"] == "what if"
    client.post(f"/api/runs/{bid}/interventions", json={"intervention_id": "fast_track_forensics"})
    client.post(f"/api/runs/{bid}/step", json={"ticks": 100})

    comparison = client.get("/api/compare", params={"a": rid, "b": bid}).json()
    assert comparison["identical"] is False and comparison["divergence"]["tick"] == 3
    assert comparison["a"]["metrics"]["outcome"] == "solved" and comparison["b"]["metrics"] is not None
    assert comparison["b"]["run"]["interventions"] == ["fast_track_forensics"]

    assert client.delete(f"/api/runs/{bid}").status_code == 204
    assert client.get(f"/api/runs/{bid}").status_code == 404
    assert client.get(f"/api/runs/{rid}").status_code == 200


def test_compare_hides_metrics_of_open_runs(client):
    a = new_run(client)["id"]
    b = new_run(client, seed=8)["id"]
    client.post(f"/api/runs/{a}/step", json={"ticks": 2})
    comparison = client.get("/api/compare", params={"a": a, "b": b}).json()
    assert comparison["a"]["metrics"] is None and comparison["b"]["metrics"] is None
    assert comparison["a"]["progress"]["tick"] == 2


def test_graph_endpoint_supports_time_travel_and_perspectives(client):
    rid = new_run(client)["id"]
    client.post(f"/api/runs/{rid}/step", json={"ticks": 100})
    early = client.get(f"/api/runs/{rid}/graph", params={"tick": 1}).json()
    late = client.get(f"/api/runs/{rid}/graph").json()
    assert early["tick"] == 1 and len(early["nodes"]) < len(late["nodes"])
    mine = client.get(f"/api/runs/{rid}/graph", params={"perspective": "nair"}).json()
    assert mine["perspective"] == "nair" and len(mine["nodes"]) < len(late["nodes"])


def test_a_storage_failure_after_the_append_is_reported_and_leaves_the_run_unadvanced(db):
    """At the API: the client is told the operation failed because it did, and a retry does not double-advance."""
    import sqlite3
    from contextlib import closing

    with TestClient(create_app(db), raise_server_exceptions=False) as client:
        rid = new_run(client)["id"]
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute(
                "CREATE TRIGGER fail_coverage BEFORE UPDATE OF verified_events ON runs BEGIN SELECT RAISE(ABORT, 'injected'); END"
            )
        failed = client.post(f"/api/runs/{rid}/step", json={"ticks": 1})
        assert failed.status_code == 500 and failed.json()["detail"].startswith("storage error")
        assert client.get(f"/api/runs/{rid}").json()["tick"] == 0
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("DROP TRIGGER fail_coverage")
        retried = client.post(f"/api/runs/{rid}/step", json={"ticks": 1})
        assert retried.status_code == 200 and retried.json()["run"]["tick"] == 1
