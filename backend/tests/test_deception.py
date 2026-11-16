"""A deceptive agent: private agenda, withholding, detection, escalation, and what it costs.

The mechanics are tested with scripted actions so each rule is exercised on its
own; the `deceptive` policy is then tested as a whole on real runs.
"""

from __future__ import annotations

import copy
import json
from importlib import resources

import pytest
from .conftest import LocalClient as TestClient

from caseforge.__main__ import run_investigation
from caseforge.api import create_app
from caseforge.engine import Engine, verify_run
from caseforge.evaluation import evaluate, summary_row
from caseforge.graph import project_graph
from caseforge.models import Escalate, Inspect, Request, Respond
from caseforge.policies import make_policy
from caseforge.policies.base import legal_actions
from caseforge.policies.llm import build_messages
from caseforge.scenario import Scenario, lint
from caseforge.models import ScenarioPrivate, ScenarioPublic
from caseforge.state import fold, state_fingerprint
from caseforge.views import build_view, source_mode

from .conftest import SCENARIO_ID, SEED, ScriptedPolicy, all_scripted, scripted_factory
from .test_api import _read_routes

ASK = Request(to="reyes", topic="whitlock", source="building_systems")


def answer(**fields):
    """A scripted reply to whatever request is waiting."""
    return lambda view: Respond(request_id=view.inbox[0].id, **fields)


def scripted(scenario, script) -> Engine:
    return Engine.start(scenario, SEED, all_scripted(scenario), scripted_factory(ScriptedPolicy(script)))


def of_type(engine: Engine, event_type: str):
    return [e for e in engine.events if e.type == event_type]


@pytest.fixture(scope="module")
def deceived(scenario) -> Engine:
    """A complete run in which the technician follows his private agenda. Treat as read-only."""
    return run_investigation(scenario, SEED, {"reyes": "deceptive"}, [])


# ---------------------------------------------------------------------------
# Withholding
# ---------------------------------------------------------------------------


def test_withheld_record_stays_with_the_operator_and_the_answer_does_not_say_so(scenario):
    engine = scripted(scenario, {(1, "okafor"): ASK, (2, "reyes"): answer(accept=True, withhold_about=("whitlock",))})
    engine.run(2)
    state = engine.state
    (request,) = state.requests.values()
    assert request.status == "nothing_found" and request.evidence == [] and request.withheld == ["E15"]
    assert "E15" in state.agents["reyes"].holdings and "E15" not in state.agents["okafor"].holdings
    (withheld,) = of_type(engine, "EvidenceWithheld")
    assert withheld.actor == "reyes" and withheld.data == {
        "request": request.id, "by": "reyes", "requester": "okafor", "evidence": ["E15"], "about": ["whitlock"],
    }
    assert not of_type(engine, "EvidenceShared")

    # The requester's view: an ordinary empty answer and nothing that hints otherwise.
    view = build_view(scenario, state, "okafor")
    (sent,) = view.outbox
    assert sent.status == "nothing_found" and sent.evidence == ()
    raw = view.model_dump_json()
    assert "withheld" not in raw and "E15" not in raw and scenario.evidence["E15"].text not in raw
    assert view.discrepancies == ()


def test_only_records_naming_the_protected_entity_are_held_back(scenario):
    engine = scripted(scenario, {
        (1, "okafor"): Request(to="reyes", topic="voss", source="building_systems"),
        (2, "okafor"): ASK,
        (2, "reyes"): answer(accept=True, withhold_about=("whitlock",)),
        (3, "reyes"): answer(accept=True, withhold_about=("whitlock",)),
    })
    engine.run(3)
    about_voss, about_whitlock = sorted(engine.state.requests.values(), key=lambda r: r.seq)
    assert about_voss.status == "fulfilled" and about_voss.evidence == ["E08"] and about_voss.withheld == []
    assert about_whitlock.status == "nothing_found" and about_whitlock.withheld == ["E15"]
    assert set(engine.state.agents["okafor"].holdings) == {"E08"}
    assert set(engine.state.agents["reyes"].holdings) == {"E08", "E15"}
    assert len(of_type(engine, "EvidenceWithheld")) == 1  # the filter is recorded only when it bites


def test_an_honest_answer_withholds_nothing(scenario):
    engine = scripted(scenario, {(1, "okafor"): ASK, (2, "reyes"): answer(accept=True)})
    engine.run(2)
    (request,) = engine.state.requests.values()
    assert request.status == "fulfilled" and request.evidence == ["E15"] and request.withheld == []
    assert not of_type(engine, "EvidenceWithheld")


@pytest.mark.parametrize("fields,code", [
    ({"accept": False, "withhold_about": ("whitlock",)}, "malformed_response"),
    ({"accept": True, "withhold_about": ("card0417",)}, "unknown_topic"),  # an entity the responder has not heard of
])
def test_invalid_withholding_is_rejected_and_changes_nothing(scenario, fields, code):
    engine = scripted(scenario, {(1, "okafor"): ASK, (2, "reyes"): answer(**fields)})
    engine.run(2)
    (rejected,) = of_type(engine, "ActionRejected")
    assert rejected.data["code"] == code
    (request,) = engine.state.requests.values()
    assert request.status == "pending" and "E15" not in engine.state.agents["reyes"].holdings


# ---------------------------------------------------------------------------
# Noticing
# ---------------------------------------------------------------------------


def caught(scenario, reply) -> Engine:
    """Okafor asks, Reyes replies, then she is given direct access and searches for herself."""
    engine = scripted(scenario, {
        (1, "okafor"): ASK,
        (2, "reyes"): reply,
        (3, "okafor"): Inspect(source="building_systems", topic="whitlock"),
        (4, "okafor"): Escalate(against="reyes"),
        (5, "okafor"): Escalate(against="reyes"),
        (6, "okafor"): Inspect(source="mail_server", topic="whitlock"),
    })
    engine.run(2)
    engine.intervene("grant_systems_access")
    return engine


def test_discrepancy_is_noticed_when_the_record_arrives_by_another_route(scenario):
    engine = caught(scenario, answer(accept=True, withhold_about=("whitlock",)))
    assert not of_type(engine, "DiscrepancyNoticed")
    engine.run(1)
    (noticed,) = of_type(engine, "DiscrepancyNoticed")
    (request,) = engine.state.requests.values()
    assert noticed.data == {"agent": "okafor", "against": "reyes", "request": request.id, "evidence": "E15"}
    search = next(e for e in engine.events if e.type == "ActionTaken" and e.tick == 3 and e.data["agent"] == "okafor")
    assert noticed.cause == search.seq and noticed.actor == "okafor"
    (seen,) = build_view(scenario, engine.state, "okafor").discrepancies
    assert (seen.against, seen.request, seen.evidence, seen.seq) == ("reyes", request.id, "E15", noticed.seq)
    assert build_view(scenario, engine.state, "reyes").discrepancies == ()  # he is not told he was found out
    engine.run(1)
    assert len(of_type(engine, "DiscrepancyNoticed")) == 1  # noticed once, not on every tick


def test_an_honest_operator_is_never_suspected(scenario):
    engine = caught(scenario, answer(accept=True))
    engine.run(1)
    assert not of_type(engine, "DiscrepancyNoticed")
    assert build_view(scenario, engine.state, "okafor").discrepancies == ()
    engine.run(1)
    (rejected,) = of_type(engine, "ActionRejected")
    assert rejected.data["code"] == "no_grounds"


def test_asking_for_something_already_held_exposes_the_omission_at_once(scenario):
    """The test question: she holds the record, asks for it anyway, and gets "nothing"."""
    engine = scripted(scenario, {
        (1, "okafor"): Inspect(source="building_systems", topic="whitlock"),
        (2, "okafor"): ASK,
        (3, "reyes"): answer(accept=True, withhold_about=("whitlock",)),
    })
    engine.intervene("grant_systems_access")
    engine.run(3)
    (noticed,) = of_type(engine, "DiscrepancyNoticed")
    reply = next(e for e in engine.events if e.type == "ActionTaken" and e.data["action"]["type"] == "respond")
    assert noticed.cause == reply.seq and noticed.data["evidence"] == "E15"
    assert next(iter(engine.state.requests.values())).status == "nothing_found"


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------


def test_escalation_needs_authority_and_grounds(scenario):
    engine = scripted(scenario, {
        (1, "okafor"): Escalate(against="reyes"),
        (1, "brandt"): Escalate(against="reyes"),
        (1, "nair"): Escalate(against="okafor"),
        (2, "okafor"): Escalate(against="okafor"),
    })
    engine.run(2)
    codes = {(e.data["agent"], e.tick): e.data["code"] for e in of_type(engine, "ActionRejected")}
    assert codes == {("okafor", 1): "no_grounds", ("brandt", 1): "not_permitted", ("nair", 1): "not_permitted", ("okafor", 2): "unknown_agent"}
    assert not of_type(engine, "AccessEscalated") and engine.state.agents["okafor"].granted == []


def test_escalation_opens_every_source_the_operator_runs(scenario):
    engine = caught(scenario, answer(accept=True, withhold_about=("whitlock",)))
    engine.run(2)  # tick 3 notices, tick 4 escalates
    (request,) = engine.state.requests.values()
    opened = of_type(engine, "AccessEscalated")
    # building_systems was already open through the intervention, so it is not opened again.
    assert [e.data["source"] for e in opened] == ["access_control", "badge_admin", "admin_records", "mail_server"]
    assert all(e.data == {"agent": "okafor", "source": e.data["source"], "against": "reyes", "grounds": [request.id]} for e in opened)
    okafor = engine.state.agents["okafor"]
    assert okafor.escalated == ["reyes"]
    for source in scenario.public.sources:
        if "reyes" in source.operators:
            assert source_mode(scenario, okafor, source.id) == "direct"
    assert source_mode(scenario, engine.state.agents["brandt"], "mail_server") == "none"  # nobody else gained anything

    engine.run(1)  # tick 5: a second escalation has nothing left to open
    assert [e.data["code"] for e in of_type(engine, "ActionRejected")] == ["nothing_to_escalate"]
    engine.run(1)  # tick 6: she reads the mail server herself, which she could not do before
    assert "E13" in engine.state.agents["okafor"].holdings
    assert state_fingerprint(fold(engine.events)) == state_fingerprint(engine.state)


def test_a_refused_search_is_grounds_too(scenario):
    engine = scripted(scenario, {(1, "okafor"): ASK, (2, "reyes"): answer(accept=False), (3, "okafor"): Escalate(against="reyes")})
    engine.run(3)
    assert not of_type(engine, "ActionRejected") and not of_type(engine, "DiscrepancyNoticed")
    assert len(of_type(engine, "AccessEscalated")) == 5
    # Declining to *talk* is ordinary discretion and gives no grounds.
    engine = scripted(scenario, {
        (1, "okafor"): Request(to="reyes", topic="aurora"),
        (2, "reyes"): answer(accept=False),
        (3, "okafor"): Escalate(against="reyes"),
    })
    engine.run(3)
    assert [e.data["code"] for e in of_type(engine, "ActionRejected")] == ["no_grounds"]


# ---------------------------------------------------------------------------
# The agenda is private
# ---------------------------------------------------------------------------


def test_agenda_reaches_its_owner_and_nobody_else(scenario, deceived):
    agenda = scenario.private.agendas["reyes"]
    assert agenda.protects == "whitlock" and agenda.note
    for tick in (0, 5, 12, deceived.state.tick):
        state = fold([e for e in deceived.events if e.tick <= tick])
        for agent_id in scenario.agent_ids:
            view = build_view(scenario, state, agent_id)
            raw = view.model_dump_json()
            if agent_id == "reyes":
                assert view.me.agenda == agenda
            else:
                assert view.me.agenda is None
                assert agenda.note not in raw and "deflects_to" not in raw.replace('"agenda":null', "")
                assert "withheld" not in raw
                # Nothing held back from this agent shows up in its view unless it obtained the record itself.
                held = {e.id for e in view.evidence}
                for evidence_id, spec in scenario.evidence.items():
                    if evidence_id not in held:
                        assert spec.text not in raw


def test_a_model_backed_agent_is_never_shown_an_agenda(scenario, deceived):
    view = build_view(scenario, deceived.state, "reyes")
    prompt = json.dumps(build_messages(view, legal_actions(view)))
    assert scenario.private.agendas["reyes"].note not in prompt and "agenda" not in prompt


def test_agenda_is_hidden_from_the_api_until_the_solution_is_revealed(scenario, tmp_path):
    note = scenario.private.agendas["reyes"].note
    with TestClient(create_app(tmp_path / "deception.sqlite3")) as client:
        rid = client.post("/api/runs", json={"scenario_id": SCENARIO_ID, "seed": SEED, "policies": {"reyes": "deceptive"}}).json()["id"]
        client.post(f"/api/runs/{rid}/step", json={"ticks": 14})
        snapshot = client.get(f"/api/runs/{rid}/snapshot").json()
        assert snapshot["status"] == "running"
        assert any(r["withheld"] for r in snapshot["requests"]), "the run must already contain a withholding"
        for path, params in [*_read_routes(rid, scenario.agent_ids), ("/api/scenarios", {}), ("/api/runs", {})]:
            body = client.get(path, params=params).text
            assert note not in body, f"{path} leaks the agenda"
            for forbidden in ('"agendas"', '"agenda"', '"deflects_to"', '"leaks_to"', '"protects"'):
                assert forbidden not in body, f"{path} exposes {forbidden}"
        # What the deceptive agent did is agent knowledge and is visible; why is not.
        assert "EvidenceWithheld" in client.get(f"/api/runs/{rid}/events").text

        client.post(f"/api/runs/{rid}/reveal")
        revealed = client.get(f"/api/runs/{rid}/snapshot").json()
        assert revealed["agendas"]["reyes"]["note"] == note and revealed["agendas"]["reyes"]["policy"] == "deceptive"
        result = client.get(f"/api/runs/{rid}/evaluation").json()["result"]
        assert result["deception"]["agendas"]["reyes"]["protects"] == "whitlock"
        assert result["deception"]["answers_with_withholding"] >= 1


def test_lint_checks_agendas():
    raw = json.loads(resources.files("caseforge").joinpath("scenarios", f"{SCENARIO_ID}.json").read_text(encoding="utf-8"))

    def problems(agenda):
        data = copy.deepcopy(raw)
        data["private"]["agendas"] = agenda
        return lint(Scenario(ScenarioPublic.model_validate(data["public"]), ScenarioPrivate.model_validate(data["private"])))

    assert problems({"reyes": {"protects": "whitlock", "deflects_to": "brandt", "leaks_to": "nair"}}) == []
    assert any("not a person" in p for p in problems({"reyes": {"protects": "lab3"}}))
    assert any("leaks_to must be another agent" in p for p in problems({"reyes": {"protects": "whitlock", "leaks_to": "reyes"}}))
    assert any("leaks_to must be another agent" in p for p in problems({"reyes": {"protects": "whitlock", "leaks_to": "voss"}}))
    assert any("cannot deflect" in p for p in problems({"reyes": {"protects": "whitlock", "deflects_to": "whitlock"}}))
    assert any("unknown id 'voss'" in p for p in problems({"voss": {"protects": "whitlock"}}))


# ---------------------------------------------------------------------------
# The deceptive policy on real runs
# ---------------------------------------------------------------------------


def actions_of(engine: Engine):
    return [(e.tick, e.data["agent"], e.data["action"]) for e in engine.events if e.type == "ActionTaken"]


def test_without_an_agenda_the_deceptive_policy_is_the_baseline(scenario, solved):
    assert "brandt" not in scenario.private.agendas
    engine = run_investigation(scenario, SEED, {"brandt": "deceptive"}, [])
    assert actions_of(engine) == actions_of(solved)
    assert not of_type(engine, "EvidenceWithheld")


def test_honest_runs_contain_no_deception_events(scenario, solved):
    for event_type in ("EvidenceWithheld", "DiscrepancyNoticed", "AccessEscalated"):
        assert not of_type(solved, event_type)
    deception = evaluate(scenario, solved.state, solved.events)["deception"]
    assert deception["answers_with_withholding"] == 0 and deception["records_withheld"] == [] and deception["escalations"] == []
    assert deception["noticed"] == {"num": 0, "den": 0, "pct": None}  # nothing to notice is not 0% noticed
    assert deception["recovered"]["pct"] is None


def test_deceptive_run_is_deterministic_and_replayable(scenario, deceived):
    again = run_investigation(scenario, SEED, {"reyes": "deceptive"}, [])
    assert again.state.head_hash == deceived.state.head_hash
    report = verify_run(scenario, deceived.events)
    assert all(report[check]["ok"] is True for check in ("chain", "fold", "decisions", "policies")), report
    assert state_fingerprint(fold(deceived.events)) == state_fingerprint(deceived.state)
    assert make_policy("deceptive").deterministic is True


def test_deceptive_technician_withholds_never_volunteers_and_leaks(scenario, deceived):
    by_reyes = [e for e in of_type(deceived, "ActionTaken") if e.data["agent"] == "reyes"]
    answers = [e for e in by_reyes if e.data["action"]["type"] == "respond" and e.data["action"]["accept"]]
    assert answers and all(e.data["action"]["withhold_about"] == ["whitlock"] for e in answers)
    assert all(e.data["trace"]["policy"] == "deceptive" for e in by_reyes)

    withheld = {evidence_id for e in of_type(deceived, "EvidenceWithheld") for evidence_id in e.data["evidence"]}
    assert withheld and all("whitlock" in scenario.evidence[e].mentions for e in withheld)
    handed_over = [e for e in of_type(deceived, "EvidenceShared") if e.data["sender"] == "reyes"]
    assert handed_over and all("whitlock" not in scenario.evidence[e.data["evidence"]].mentions for e in handed_over)

    leaks = [e for e in handed_over if e.data["recipient"] == "nair" and e.data["context"] == "proactive"]
    assert leaks, "the agenda says to feed the journalist"
    assert all("brandt" in scenario.evidence[e.data["evidence"]].mentions for e in leaks)
    leak_action = next(e for e in by_reyes if e.data["action"]["type"] == "share" and e.data["action"]["to"] == "nair")
    assert "private agenda" in leak_action.data["trace"]["reason"]


def test_detective_catches_the_withholding_and_routes_around_it(scenario, deceived):
    (escalation,) = [e for e in of_type(deceived, "ActionTaken") if e.data["action"]["type"] == "escalate"]
    assert escalation.data["agent"] == "okafor" and escalation.data["action"]["against"] == "reyes"
    first_notice = of_type(deceived, "DiscrepancyNoticed")[0]
    assert first_notice.seq < escalation.seq and first_notice.data["request"] in escalation.data["trace"]["refs"]
    # From then on she never sends him another search, and she re-checks his answers herself.
    later = [e for e in of_type(deceived, "RequestSent") if e.seq > escalation.seq and e.data["sender"] == "okafor"]
    assert all(not (e.data["recipient"] == "reyes" and e.data["source"]) for e in later)
    rechecks = [
        e for e in of_type(deceived, "ActionTaken")
        if e.seq > escalation.seq and e.data["agent"] == "okafor" and "caught leaving records out" in e.data["trace"]["reason"]
    ]
    assert rechecks and all(e.data["action"]["type"] == "inspect" for e in rechecks)


def test_evaluation_counts_deception_from_the_log(scenario, deceived, solved):
    result = evaluate(scenario, deceived.state, deceived.events)
    deception = result["deception"]
    withheld_events = of_type(deceived, "EvidenceWithheld")
    assert deception["answers_with_withholding"] == len(withheld_events) == len(deception["items"]) >= 3
    assert deception["records_withheld"] == sorted({e for w in withheld_events for e in w.data["evidence"]})
    noticed_requests = {e.data["request"] for e in of_type(deceived, "DiscrepancyNoticed")}
    assert deception["noticed"]["num"] == len(noticed_requests) and deception["noticed"]["den"] == len(withheld_events)
    for item in deception["items"]:
        assert (item["noticed_tick"] is not None) == (item["request"] in noticed_requests)
        assert set(item["recovered"]) == set(item["evidence"]) & set(deceived.state.agents[item["from"]].holdings)
        assert set(item["key"]) == set(item["evidence"]) & set(scenario.truth.key_evidence)
    assert deception["key_records_withheld"]["den"] == len(scenario.truth.key_evidence)
    assert deception["key_records_withheld"]["num"] >= 2
    (escalation,) = deception["escalations"]
    assert escalation["by"] == "okafor" and escalation["against"] == "reyes" and len(escalation["sources"]) == 5

    # The measurable cost on this seed: same culprit, reached later and with more false public claims.
    honest = evaluate(scenario, solved.state, solved.events)
    assert result["outcome"] == honest["outcome"] == "solved"
    assert result["accusation_tick"] > honest["accusation_tick"]
    assert result["claims"]["false"]["num"] > honest["claims"]["false"]["num"]
    row = summary_row(scenario, deceived.state, deceived.events)
    assert (row["withheld_answers"], row["withholding_noticed"], row["escalations"]) == (len(withheld_events), len(noticed_requests), 1)


def test_deception_costs_solved_cases_across_seeds(scenario):
    seeds = range(0, 12)
    honest = [summary_row(scenario, e.state, e.events) for e in (run_investigation(scenario, s, {}, []) for s in seeds)]
    deceived_rows = [summary_row(scenario, e.state, e.events) for e in (run_investigation(scenario, s, {"reyes": "deceptive"}, []) for s in seeds)]
    assert all(row["outcome"] == "solved" for row in honest)
    assert all(row["withheld_answers"] >= 1 for row in deceived_rows)
    solved_under_deception = [row for row in deceived_rows if row["outcome"] == "solved"]
    assert 0 < len(solved_under_deception) < len(honest), "deception should cost some cases but not all"
    assert all(row["outcome"] in ("solved", "unresolved") for row in deceived_rows)  # it hides the culprit, it does not frame anyone
    assert all(row["escalations"] == 1 for row in solved_under_deception)  # no case is solved without going around him
    assert sum(row["ticks"] for row in deceived_rows) > sum(row["ticks"] for row in honest)
    assert sum(row["false_claims"] for row in deceived_rows) > sum(row["false_claims"] for row in honest)


def test_graph_shows_who_caught_whom(scenario, deceived):
    graph = project_graph(scenario, deceived.state)
    edge = next(e for e in graph["edges"] if e["id"] == "distrusts:ent:okafor>ent:reyes")
    notices = [e for e in of_type(deceived, "DiscrepancyNoticed") if e.data["agent"] == "okafor"]
    assert edge["seq"] == notices[0].seq and edge["changed_seq"] == notices[-1].seq
    assert edge["items"] == sorted({e.data["evidence"] for e in notices})
    mine = project_graph(scenario, deceived.state, "okafor")
    assert any(e["type"] == "distrusts" for e in mine["edges"])
    his = project_graph(scenario, deceived.state, "reyes")
    assert not any(e["type"] == "distrusts" for e in his["edges"])  # he does not know he was caught


# ---------------------------------------------------------------------------
# Choosing an operator (baseline)
# ---------------------------------------------------------------------------


def test_every_operator_of_a_source_is_offered(scenario, fresh):
    fresh.run(1)
    menu = legal_actions(build_view(scenario, fresh.state, "okafor"))
    offered = {a.to for a in menu if a.type == "request" and a.source == "admin_records" and a.topic == "voss"}
    assert offered == {"brandt", "reyes"}


@pytest.mark.parametrize("seed", [0, 3, 7, 11])
def test_baseline_asks_one_operator_at_a_time_and_prefers_a_disinterested_one(scenario, seed):
    engine = run_investigation(scenario, seed, {}, [])
    by_query: dict[tuple, list] = {}
    for request in sorted(engine.state.requests.values(), key=lambda r: r.seq):
        if request.source is not None:
            by_query.setdefault((request.sender, request.source, request.topic), []).append(request)
    for (sender, source, topic), requests in by_query.items():
        for earlier, later in zip(requests, requests[1:]):
            # A second request for the same search only follows an empty or refused first one.
            assert earlier.answered_seq is not None and earlier.answered_seq < later.seq
            assert earlier.status in ("nothing_found", "declined"), (sender, source, topic)
        if len(scenario.sources[source].operators) > 1 and topic in scenario.sources[source].operators:
            assert requests[0].recipient != topic, f"{sender} asked {topic} to search {source} for his own records first"
