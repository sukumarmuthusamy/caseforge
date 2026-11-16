"""The laboratory as the web interface reads it: stored results, bounded execution, ground-truth gating."""

from __future__ import annotations

import copy
import json

import pytest
from .conftest import LocalClient as TestClient

from caseforge import lab
from caseforge.api import create_app
from caseforge.lab_service import KNOWN_LIMITATIONS, MAX_EXECUTE_SEEDS, LabService, default_results_path

from .test_challenge import LIMITS

pytestmark = pytest.mark.skipif(not default_results_path().is_file(), reason="the recorded collection ships with the repository")

CHALLENGES = [c["id"] for c in lab.default_manifest()["challenges"]]


@pytest.fixture()
def client(tmp_path):
    with TestClient(create_app(tmp_path / "lab.sqlite3")) as c:
        yield c


def served(tmp_path, **kwargs):
    return TestClient(create_app(tmp_path / "lab.sqlite3", lab_service=LabService(**kwargs)))


def ids(entries):
    return [e["id"] for e in entries]


# -- what is read ---------------------------------------------------------------------------------


def test_overview_reports_the_recorded_collection_as_recorded(client):
    body = client.get("/api/lab").json()
    manifest = lab.default_manifest()
    assert ids(body["playable"]) == [c["id"] for c in manifest["challenges"] if c["kind"] == "playable"]
    assert ids(body["reasoning"]) == [c["id"] for c in manifest["challenges"] if c["kind"] == "reasoning"]
    assert body["stored"]["available"] and body["stored"]["problem"] is None
    assert body["stored"]["runs"] == 520 and body["stored"]["replay_passed"] == 520
    assert body["stored"]["seeds"] == [0, 39] and body["stored"]["replay"] == "every"
    assert body["drift"] == [] and body["can_execute"] is True
    # Playable and reasoning-only predictions are counted in separate tables, never summed.
    assert body["predictions"] == {"playable": {"right": 65, "of": 69}, "reasoning": {"right": 16, "of": 16}}
    assert [(w["challenge"], w["expectation"]) for w in body["wrong_predictions"]] == [
        ("custodian_hasty", "registrar_not_accused"), ("lie_survives", "lie_not_accepted"),
        ("more_witnesses_hasty", "curator_not_accused"), ("more_witnesses_hasty", "solved_with_support"),
    ]
    assert "not an independent benchmark" in body["label"].lower()
    assert any("not a statement that the accusation is true" in note for note in body["notes"])


def test_overview_numbers_are_the_recorded_ones(client):
    stored = json.loads(default_results_path().read_text(encoding="utf-8"))
    body = client.get("/api/lab").json()
    for entry in body["playable"]:
        recorded = stored["playable"][entry["id"]]["aggregate"]
        assert entry["aggregate"]["categories"] == recorded["categories"]
        assert entry["aggregate"]["median_ticks"] == recorded["median_ticks"]
        assert entry["aggregate"]["false_ever_accepted"] == recorded["false_ever_accepted"]
        assert sum(entry["aggregate"]["categories"].values()) == entry["aggregate"]["runs"] == 40


def test_the_limitations_listed_are_the_recorded_ones(client):
    assert sorted(item["id"] for item in KNOWN_LIMITATIONS) == sorted(LIMITS)
    assert client.get("/api/lab").json()["limitations"] == list(KNOWN_LIMITATIONS)


def test_unknown_challenge_is_not_found(client):
    assert client.get("/api/lab/challenges/nope").status_code == 404
    assert client.post("/api/lab/challenges/nope/execute", json={"seeds": [0]}).status_code == 404
    assert client.post("/api/lab/challenges/nope/open", json={"seed": 0}).status_code == 404


# -- ground truth ---------------------------------------------------------------------------------

WITHHELD = ('"culprit"', '"ground_truth"', '"edits"', '"accused":', '"says"', '"variant_summary"', '"question"', '"prediction":')


@pytest.mark.parametrize("challenge", CHALLENGES)
def test_ground_truth_is_withheld_until_asked_for(client, challenge):
    entry = lab.find_challenge(lab.default_manifest(), challenge)
    closed = client.get(f"/api/lab/challenges/{challenge}")
    assert closed.status_code == 200 and closed.json()["revealed"] is False
    for forbidden in WITHHELD:
        assert forbidden not in closed.text, forbidden
    assert entry["question"] not in closed.text
    opened = client.get(f"/api/lab/challenges/{challenge}", params={"reveal": "true"}).json()
    assert opened["revealed"] is True
    assert opened["ground_truth"]["culprit"] == entry["culprit"]
    assert opened["ground_truth"]["question"] == entry["question"]
    if entry["kind"] == "playable":
        assert len(opened["ground_truth"]["edits"]) == len(lab.default_manifest()["variants"][entry["variant"]]["ops"])


def test_overview_never_carries_ground_truth(client):
    text = client.get("/api/lab").text
    for forbidden in ('"culprit"', '"ground_truth"', '"edits"', '"accused":', '"says"', '"question"'):
        assert forbidden not in text, forbidden


def test_a_wrong_accusation_is_recorded_without_naming_who_was_accused_until_revealed(client):
    closed = client.get("/api/lab/challenges/custodian_hasty").json()["stored"]
    assert all("accused" not in row for row in closed["runs"]) and "accused" not in closed["aggregate"]
    assert closed["aggregate"]["categories"]["wrong_supported"] == 24  # the verdict is still visible
    opened = client.get("/api/lab/challenges/custodian_hasty", params={"reveal": "true"}).json()["stored"]
    assert opened["aggregate"]["accused"] == {"fenwick": 24, "marsh": 16}


def test_a_reasoning_fixture_shows_its_items_and_hides_who_was_convicted(client):
    closed = client.get("/api/lab/challenges/two_records_disagree").json()
    assert closed["items"] and "convicted" not in closed["stored"]["result"] and "prime_suspect" not in closed["stored"]["result"]
    assert closed["stored"]["result"]["beliefs"]["at(bob,cafe,night)"]["status"] == "disputed"
    opened = client.get("/api/lab/challenges/two_records_disagree", params={"reveal": "true"}).json()
    assert opened["stored"]["result"]["convicted"] is None and opened["stored"]["result"]["prime_suspect"] == "bob"


# -- executing ------------------------------------------------------------------------------------


def test_nothing_runs_until_it_is_asked_for(client, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("reading must not run an investigation")

    monkeypatch.setattr(lab, "run_playable", forbidden)
    monkeypatch.setattr(lab, "run_reasoning", forbidden)
    assert client.get("/api/lab").status_code == 200
    for challenge in CHALLENGES:
        assert client.get(f"/api/lab/challenges/{challenge}").status_code == 200
    assert client.get("/api/runs").json() == []


def test_executing_a_few_seeds_reproduces_the_recorded_runs(client):
    body = client.post("/api/lab/challenges/lie_survives/execute", json={"seeds": [0, 5, 39], "replay": True}).json()
    assert body["source"] == "executed" and body["replay"] is True and "Not the recorded collection" in body["label"]
    assert [row["seed"] for row in body["runs"]] == [0, 5, 39]
    assert all(row["replay"] == {"chain": True, "fold": True, "decisions": True, "policies": True} for row in body["runs"])
    assert body["compared_with_stored"] == {"compared": 3, "identical": 3, "different_seeds": []}
    assert body["aggregate"]["runs"] == 3 and "accused" not in body["runs"][0]


def test_executing_is_deterministic_and_leaves_no_run_behind(client):
    first = client.post("/api/lab/challenges/control/execute", json={"seeds": [1, 2]}).json()
    second = client.post("/api/lab/challenges/control/execute", json={"seeds": [1, 2]}).json()
    assert first == second and first["replay"] is False and first["runs"][0]["replay"] is None
    assert client.get("/api/runs").json() == []


def test_executing_a_reasoning_fixture_matches_the_recorded_result(client):
    body = client.post("/api/lab/challenges/two_keyholders/execute", json={}).json()
    assert body["source"] == "executed" and body["compared_with_stored"] == {"compared": 1, "identical": 1, "different_seeds": []}


@pytest.mark.parametrize("seeds", [[], list(range(MAX_EXECUTE_SEEDS + 1)), [3, 3], [-1], [2**31]])
def test_executing_is_bounded_and_validated(client, seeds):
    response = client.post("/api/lab/challenges/control/execute", json={"seeds": seeds})
    assert response.status_code in (400, 422), response.text
    assert client.get("/api/runs").json() == []


def test_executing_cannot_be_given_another_policy(client):
    response = client.post("/api/lab/challenges/control/execute", json={"seeds": [0], "policies": {"hale": "llm"}})
    assert response.status_code == 200  # an unknown field is ignored, and the registered policies run
    assert response.json()["runs"][0]["seed"] == 0
    assert client.get("/api/health").json()["llm_calls_used"] == 0


def test_executing_refuses_when_the_build_is_not_the_registered_one(tmp_path):
    manifest = copy.deepcopy(lab.default_manifest())
    manifest["frozen"]["rules_version"] = "an-older-rule-set"
    drifted = served(tmp_path, manifest=manifest)
    overview = drifted.get("/api/lab").json()
    assert overview["can_execute"] is False and any("rules_version" in line for line in overview["drift"])
    refused = drifted.post("/api/lab/challenges/control/execute", json={"seeds": [0]})
    assert refused.status_code == 409 and "registered against" in refused.json()["detail"]
    assert drifted.get("/api/runs").json() == []


def test_only_one_laboratory_run_at_a_time(tmp_path):
    service = LabService()
    app = TestClient(create_app(tmp_path / "x.sqlite3", lab_service=service))
    assert service._busy.acquire(blocking=False)
    try:
        response = app.post("/api/lab/challenges/control/execute", json={"seeds": [0]})
    finally:
        service._busy.release()
    assert response.status_code == 409 and "still going" in response.json()["detail"]
    assert app.post("/api/lab/challenges/control/execute", json={"seeds": [0]}).status_code == 200


# -- stored results that cannot be trusted ----------------------------------------------------------


def test_missing_recorded_results_are_reported_not_invented(tmp_path):
    app = served(tmp_path, results_path=tmp_path / "absent.json")
    overview = app.get("/api/lab").json()
    assert overview["stored"]["available"] is False and "no recorded results" in overview["stored"]["problem"]
    assert overview["predictions"] == {"playable": {"right": 0, "of": 0}, "reasoning": {"right": 0, "of": 0}}
    assert all(e["aggregate"] is None for e in overview["playable"])
    detail = app.get("/api/lab/challenges/control").json()
    assert detail["stored"] is None and detail["source"] is None and detail["setup"]["scenario_id"] == "quiet_substitution.control"
    assert app.post("/api/lab/challenges/control/execute", json={"seeds": [0]}).json()["compared_with_stored"] is None


@pytest.mark.parametrize("edit, expected", [
    (lambda r: r.update(manifest_version=999), "version this build does not read"),
    (lambda r: r["registered_against"].update(rules_version="other"), "different registration"),
    (lambda r: r["playable"].update(invented=r["playable"]["control"]), "does not have"),
])
def test_recorded_results_of_another_registration_are_not_used(tmp_path, edit, expected):
    results = json.loads(default_results_path().read_text(encoding="utf-8"))
    edit(results)
    path = tmp_path / "results.json"
    path.write_text(json.dumps(results), encoding="utf-8")
    overview = served(tmp_path, results_path=path).get("/api/lab").json()
    assert overview["stored"]["available"] is False and expected in overview["stored"]["problem"]


def test_unreadable_recorded_results_are_reported(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{ not json", encoding="utf-8")
    overview = served(tmp_path, results_path=path).get("/api/lab").json()
    assert overview["stored"]["available"] is False and "cannot be read" in overview["stored"]["problem"]


# -- opening a challenge as an ordinary run ---------------------------------------------------------


def test_a_challenge_opens_as_an_ordinary_run_that_persists_and_replays(tmp_path):
    db = tmp_path / "open.sqlite3"
    app = TestClient(create_app(db))
    opened = app.post("/api/lab/challenges/custodian_hasty/open", json={"seed": 3})
    assert opened.status_code == 201
    run = opened.json()["run"]
    assert run["scenario_id"] == "quiet_substitution.custodian" and run["policies"]["hale"] == "hasty"
    assert run["label"] == "lab: custodian_hasty, seed 3" and run["continuable"] and run["compatibility"]["state"] == "current"
    final = app.post(f"/api/runs/{run['id']}/step", json={"ticks": 100}).json()["run"]
    assert final["status"] == "closed"
    stored = json.loads(default_results_path().read_text(encoding="utf-8"))["playable"]["custodian_hasty"]["runs"][3]
    assert final["head_hash"] == stored["head"], "the opened run is the recorded run: same head hash"
    assert app.get(f"/api/runs/{run['id']}/verify").json()["policies"]["ok"] is True
    assert app.get(f"/api/runs/{run['id']}/evaluation").json()["available"] is True
    # A run of a variant survives a restart and can be branched like any other.
    again = TestClient(create_app(db))
    listed = again.get("/api/runs").json()
    assert [r["id"] for r in listed] == [run["id"]] and listed[0]["compatible"] is True
    branch = again.post(f"/api/runs/{run['id']}/branch", json={"tick": 4})
    assert branch.status_code == 201 and branch.json()["scenario_id"] == "quiet_substitution.custodian"


def test_opening_names_the_registered_interventions(client):
    scheduled = [c for c in lab.default_manifest()["challenges"] if c.get("interventions")]
    for challenge in scheduled:
        body = client.post(f"/api/lab/challenges/{challenge['id']}/open", json={"seed": 0}).json()
        assert [(i["intervention_id"], i["after_tick"]) for i in body["registered_interventions"]] == sorted((n, t) for n, t in challenge["interventions"])


def test_a_reasoning_fixture_cannot_be_opened_as_a_run(client):
    response = client.post("/api/lab/challenges/two_keyholders/open", json={"seed": 0})
    assert response.status_code == 400 and "reasoning-only" in response.json()["detail"]
    assert client.get("/api/runs").json() == []


def test_laboratory_variants_are_not_offered_as_new_scenarios(client):
    assert [s["id"] for s in client.get("/api/scenarios").json()] == ["missing_prototype", "quiet_substitution"]
    assert client.post("/api/runs", json={"scenario_id": "quiet_substitution.nope", "seed": 1}).status_code == 404


def test_who_the_accuser_distrusted_is_a_count_until_revealed(client):
    closed = client.get("/api/lab/challenges/custodian_hasty").json()["stored"]["runs"][0]
    assert "impeached_by_accuser" not in closed and closed["impeached_by_accuser_count"] == 3
    opened = client.get("/api/lab/challenges/custodian_hasty", params={"reveal": "true"}).json()["stored"]["runs"][0]
    assert opened["impeached_by_accuser"] == ["alder", "marsh", "pruitt"] and "impeached_by_accuser_count" not in opened


def test_the_interface_renames_the_decisive_item_counts_but_not_their_values(client):
    stored = json.loads(default_results_path().read_text(encoding="utf-8"))["playable"]["control"]["runs"][0]
    shown = client.get("/api/lab/challenges/control").json()["stored"]["runs"][0]
    assert "key_evidence" not in shown and shown["decisive_found"] == stored["key_evidence"]
    assert shown["decisive_held_by_accuser"] == stored["key_evidence_held_by_accuser"]


# -- a challenge id is one validated path segment -------------------------------------------------

@pytest.mark.parametrize(
    "crafted",
    ["control%3Freveal%3Dtrue", "control%26reveal%3Dtrue", "Control", "control%20", "control.json", "..%2Fcontrol", "a" * 65, "control%00"],
)
def test_a_crafted_challenge_id_is_refused_and_never_reveals(client, crafted):
    for response in (
        client.get(f"/api/lab/challenges/{crafted}"),
        client.post(f"/api/lab/challenges/{crafted}/execute", json={"seeds": [0]}),
        client.post(f"/api/lab/challenges/{crafted}/open", json={"seed": 0}),
    ):
        assert response.status_code in (404, 422), (crafted, response.status_code)
        assert "ground_truth" not in response.text and "culprit" not in response.text
    assert client.get("/api/runs").json() == []  # nothing was opened


def test_an_id_with_a_literal_query_is_a_query_not_part_of_the_id(client):
    """What an unencoded client would send: the server reads it as the redacted challenge plus a reveal flag it was explicitly given."""
    closed = client.get("/api/lab/challenges/control")
    assert closed.status_code == 200 and "ground_truth" not in closed.json()
    assert client.get("/api/lab/challenges/control?reveal=true").json()["revealed"] is True  # the observer-controlled flag, unchanged
