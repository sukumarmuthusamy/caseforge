"""The second bundled case, The Quiet Substitution.

Three kinds of test, kept apart on purpose:

1. *The puzzle on paper.* What the reference rules make of chosen sets of
   records. The expected values are worked out by hand from the weights (see
   test_reasoning_cases.py for the arithmetic) and written as literals.
2. *Play.* Whole investigations: what the detective does, whether she is
   right, and whether she is right for reasons the rules accept. The two are
   different questions, and this case has runs where the standard of proof is
   met for an innocent man.
3. *The machinery.* Everything the first case is held to: isolation of what
   agents see, no leaks through the API, replay, the graph.
"""

from __future__ import annotations

import pytest
from .conftest import LocalClient as TestClient

from caseforge.__main__ import run_investigation
from caseforge.api import create_app
from caseforge.engine import Engine, verify_run
from caseforge.evaluation import evaluate
from caseforge.graph import project_graph
from caseforge.reasoning import meets_standard, revise
from caseforge.scenario import lint, load_bundled, reach, reach_report
from caseforge.state import fold, state_fingerprint
from caseforge.views import build_view

from .test_api import _read_routes

CASE = "quiet_substitution"
SUSPECTS = ("fenwick", "marsh", "castellan", "ibarra")


@pytest.fixture(scope="module")
def case():
    return load_bundled(CASE)


def judge(case, ids):
    return revise([case.item_for(e) for e in ids], case.reasoning_context())


def convicted(result) -> list[str]:
    return [s for s in SUSPECTS if meets_standard(result.suspects, s)]


# -- 1. the puzzle on paper ---------------------------------------------------------

TRAP = ["E02", "E03", "E08", "E09", "E13"]  # the guard's two statements, Friday's key entry, the memo, the lock
KEY = ["E07", "E12", "E13", "E14", "E15", "E17"]


def test_the_case_is_well_formed_and_differs_in_kind_from_the_first(case):
    assert lint(case) == []
    assert case.truth.culprit == "marsh" and case.truth.culprit not in case.agents
    assert {a.role for a in case.public.agents} == {"detective", "registrar", "security", "examiner"}
    assert not any(a.disposition.can_publish for a in case.public.agents)  # nobody here prints anything
    predicates = {p.predicate for e in case.evidence.values() for p in e.asserts}
    assert predicates == {"at", "crime_at", "crime_used", "had", "has_motive", "took"}  # no card rule is involved
    assert len({p.args[1] for e in case.evidence.values() for p in e.asserts if p.predicate == "crime_at"}) == 2  # two rival times


def test_the_guards_account_makes_the_curator_fit_every_leg(case):
    """Friday is believed on the guard's word (2). Fenwick: seen there (2) = 3, the key (4) and the lock (5) = 2, the memo (4) = 2."""
    result = judge(case, TRAP)
    assert result.beliefs["crime_at(treasury,fri_evening)"].status == "believed"
    fenwick = result.suspects["fenwick"]
    assert (fenwick.opportunity, fenwick.means, fenwick.motive, fenwick.score) == ("strong", True, "strong", 7)
    assert result.prime_suspect == "fenwick" and convicted(result) == ["fenwick"]
    assert case.truth.culprit != "fenwick"  # the rules are satisfied, and the conclusion is false


def test_hearing_the_curator_puts_the_evening_in_doubt_and_the_case_falls_apart(case):
    """His word about the time counts 1 (he is a suspect): 2 against 1, neither evening believed."""
    result = judge(case, TRAP + ["E04"])
    assert result.beliefs["crime_at(treasury,fri_evening)"].status == "disputed"
    assert result.beliefs["crime_at(treasury,thu_evening)"].status == "disputed"
    assert result.contradictions == ["crime_at(treasury,fri_evening)|crime_at(treasury,thu_evening)"]
    fenwick = result.suspects["fenwick"]
    assert (fenwick.opportunity, fenwick.means, fenwick.score) == ("none", False, 2)  # without a time, only the motive is left
    assert result.prime_suspect is None and convicted(result) == []


def test_the_culprits_own_account_restores_the_wrong_evening(case):
    """Marsh's word adds 1 to Friday: 3 against 1 is a net of 2, and Fenwick meets the standard again."""
    result = judge(case, TRAP + ["E04", "E05"])
    assert result.beliefs["crime_at(treasury,fri_evening)"].status == "believed"
    assert result.beliefs["crime_at(treasury,thu_evening)"].status == "rejected"
    assert convicted(result) == ["fenwick"]


def test_the_logger_overturns_it_and_then_nobody_is_proved(case):
    """Thursday 4 + 1 against Friday 3. On Thursday Fenwick had neither key nor presence; Marsh is placed there only by her own word."""
    result = judge(case, TRAP + ["E04", "E05", "E12"])
    assert result.beliefs["crime_at(treasury,thu_evening)"].status == "believed"
    assert result.beliefs["crime_at(treasury,fri_evening)"].status == "rejected"
    assert result.suspects["fenwick"].score == 2 and result.suspects["fenwick"].means is False
    assert (result.suspects["marsh"].opportunity, result.suspects["marsh"].score) == ("weak", 1)
    assert result.prime_suspect is None and convicted(result) == []


def test_the_key_evidence_alone_proves_the_culprit(case):
    result = judge(case, KEY)
    marsh = result.suspects["marsh"]
    assert (marsh.opportunity, marsh.means, marsh.motive, marsh.score) == ("strong", True, "strong", 7)
    assert convicted(result) == ["marsh"]
    assert list(case.truth.key_evidence) == KEY


def test_the_dealer_has_to_be_cleared_before_the_lead_is_clear(case):
    """Castellan: the steward's sighting (2) = 3, the declined offer = 2, the letter = 1. Six against seven is no lead."""
    with_dealer = judge(case, KEY + ["E06", "E10", "E21"])
    assert with_dealer.suspects["castellan"].score == 6 and with_dealer.prime_suspect == "marsh"
    assert convicted(with_dealer) == []
    cleared = judge(case, KEY + ["E06", "E10", "E21", "E20"])  # the hall camera: 4 against 2
    assert (cleared.suspects["castellan"].opportunity, cleared.suspects["castellan"].score) == ("alibi", -1)
    assert cleared.suspects["ibarra"].score == -4
    assert convicted(cleared) == ["marsh"]


def test_the_complete_picture(case):
    result = judge(case, sorted(case.evidence))
    assert {s: result.suspects[s].score for s in SUSPECTS} == {"fenwick": -2, "marsh": 7, "castellan": -1, "ibarra": -4}
    assert convicted(result) == ["marsh"]
    assert result.contradictions == [
        "at(castellan,great_hall,thu_evening)|at(castellan,treasury_lobby,thu_evening)",
        "crime_at(treasury,fri_evening)|crime_at(treasury,thu_evening)",
    ]


def test_no_single_record_proves_anyone(case):
    for evidence_id in case.evidence:
        assert convicted(judge(case, [evidence_id])) == [], evidence_id


def test_two_routes_to_each_leg_of_the_proof(case):
    """Remove any one key record and the case still closes through another source."""
    alternates = {"E07": "E16", "E12": None, "E14": None, "E15": "E11", "E17": "E18"}  # E12 and E14 cover for each other
    for removed, substitute in alternates.items():
        ids = [e for e in KEY if e != removed] + ([substitute] if substitute else [])
        assert convicted(judge(case, ids)) == ["marsh"], removed
    assert convicted(judge(case, [e for e in KEY if e != "E13"])) == []  # the lock examination has no substitute
    assert {case.evidence[a].source for a in ("E07", "E16")} == {"key_register", "security_systems"}  # different keepers


def test_the_reach_report_tells_the_three_kinds_of_record_apart(case):
    report = reach_report(case)["accusers"]["hale"]
    assert report["solvable"] == "cooperative"
    assert report["escalation"] == ["E18"] and report["never"] == []  # the payroll note may be read, not passed on
    assert len(report["cooperative"]) == 20


# -- 2. play ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [0, 3, 7, 11])
def test_the_diligent_baseline_solves_it_within_the_cooperative_reach(case, seed):
    engine = run_investigation(case, seed, {}, [])
    result = evaluate(case, engine.state, engine.events)
    assert (result["outcome"], result["accused"], result["accusation_supported"]) == ("solved", "marsh", True)
    assert result["claims"]["published_by_agents"] == 0 and result["claims"]["false"]["pct"] is None
    found = reach(case)
    for agent_id, state in engine.state.agents.items():
        assert set(state.holdings) <= found.cooperative[agent_id], agent_id
    assert not any(e.type in ("EvidenceWithheld", "DiscrepancyNoticed", "AccessEscalated") for e in engine.events)


@pytest.mark.parametrize("seed", [3, 4])
def test_the_hasty_detective_convicts_the_curator_and_the_rules_agree(case, seed):
    """Wrong, and supported: the reference standard was met on what she held. Conformity is not correctness."""
    engine = run_investigation(case, seed, {"hale": "hasty"}, [])
    result = evaluate(case, engine.state, engine.events)
    assert (result["outcome"], result["accused"], result["culprit"]) == ("wrong_accusation", "fenwick", "marsh")
    assert result["accusation_supported"] is True
    assert "E04" not in engine.state.agents["hale"].holdings  # she never heard him


def test_the_same_seed_is_solved_once_the_accused_is_heard(case):
    engine = run_investigation(case, 3, {}, [])
    result = evaluate(case, engine.state, engine.events)
    assert result["outcome"] == "solved"
    hale = engine.state.agents["hale"].holdings
    assert hale["E04"].tick < result["accusation_tick"]


def test_when_the_culprit_speaks_first_hearing_is_not_enough_and_the_account_is_checked(case):
    """With Marsh's statement in hand, Friday survives the curator's hearing. The diligent policy then
    follows the leads in his account before naming anyone; the hasty one names him."""
    schedule = [(0, "volunteer_statement")]
    hasty = run_investigation(case, 3, {"hale": "hasty"}, schedule)
    assert evaluate(case, hasty.state, hasty.events)["outcome"] == "wrong_accusation"

    engine = run_investigation(case, 3, {}, schedule)
    result = evaluate(case, engine.state, engine.events)
    assert (result["outcome"], result["accused"], result["accusation_supported"]) == ("solved", "marsh", True)
    checks = [
        (e.tick, e.data["action"]) for e in engine.events
        if e.type == "ActionTaken" and e.data["agent"] == "hale" and "another account of when it happened" in e.data["trace"]["reason"]
    ]
    assert checks == [(11, {"type": "request", "to": "ibarra", "topic": "case_logger", "source": "environment_monitor"})]
    assert checks[0][0] < result["accusation_tick"]
    # At that moment the rules would have let her name Fenwick: the check is what stopped it.
    before = fold([e for e in engine.events if e.tick <= 10]).agents["hale"]
    assert before.prime_suspect == "fenwick" and meets_standard(before.suspects, "fenwick")


def test_a_registrar_who_shields_the_culprit_is_caught_and_bypassed(case):
    engine = run_investigation(case, 3, {"ibarra": "deceptive"}, [])
    result = evaluate(case, engine.state, engine.events)
    assert (result["outcome"], result["accused"], result["accusation_supported"]) == ("solved", "marsh", True)
    deception = result["deception"]
    assert deception["records_withheld"] == ["E11"] and deception["noticed"] == {"num": 1, "den": 1, "pct": 100}
    assert [(e["by"], e["against"], e["sources"]) for e in deception["escalations"]] == [
        ("hale", "ibarra", ["key_register", "collection_records", "environment_monitor", "hr_files"])
    ]
    # The payroll note cannot be handed over. She holds it because she searched the files herself afterwards.
    hale = engine.state.agents["hale"].holdings
    assert hale["E18"].via == "inspect" and hale["E18"].tick > deception["escalations"][0]["tick"]
    found = reach(case)
    assert "E18" not in found.cooperative["hale"]
    for agent_id, state in engine.state.agents.items():
        assert set(state.holdings) <= found.compelled[agent_id], agent_id


# -- 3. the machinery ------------------------------------------------------------------


@pytest.mark.parametrize("policies", [{}, {"hale": "hasty"}, {"ibarra": "deceptive"}], ids=["baseline", "hasty", "deceptive"])
def test_runs_replay_exactly(case, policies):
    engine = run_investigation(case, 7, policies, [])
    checks = verify_run(case, engine.events)
    assert all(checks[level]["ok"] for level in ("chain", "fold", "decisions", "policies")), checks
    again = run_investigation(case, 7, policies, [])
    assert again.state.head_hash == engine.state.head_hash
    assert state_fingerprint(fold(engine.events)) == state_fingerprint(engine.state)


def test_a_branch_of_the_second_case_reproduces_its_parent(case):
    from caseforge.engine import branch_prefix

    parent = run_investigation(case, 7, {}, [])
    twin = Engine(case, branch_prefix(parent.events, 6))
    twin.run()
    assert twin.state.head_hash == parent.state.head_hash
    changed = Engine(case, branch_prefix(parent.events, 2))
    changed.intervene("volunteer_statement")
    changed.run()
    assert changed.state.head_hash != parent.state.head_hash
    assert all(verify_run(case, changed.events)[level]["ok"] for level in ("chain", "fold", "decisions", "policies"))


@pytest.mark.parametrize("policies", [{}, {"ibarra": "deceptive"}], ids=["baseline", "deceptive"])
def test_no_view_shows_an_unheld_record_or_anothers_agenda(case, policies):
    engine = Engine.start(case, 7, policies)
    truth = case.truth
    checked = 0
    while engine.state.status == "running":
        for agent_id in case.agent_ids:
            view = build_view(case, engine.state, agent_id)
            blob = view.model_dump_json()
            held = set(engine.state.agents[agent_id].holdings)
            for evidence_id, spec in case.evidence.items():
                if evidence_id not in held:
                    assert spec.text not in blob and spec.title not in blob, f"{agent_id} can read {evidence_id} at tick {engine.state.tick}"
            assert truth.solution not in blob
            assert (view.me.agenda is not None) == (agent_id == "ibarra")
            assert case.private.agendas["ibarra"].note not in blob or agent_id == "ibarra"
            for request in view.outbox:
                assert "withheld" not in request.model_dump()
            checked += 1
        engine.step()
    assert checked > 40


def test_no_read_route_leaks_the_second_case_while_it_is_open(case, tmp_path):
    with TestClient(create_app(tmp_path / "api.sqlite3")) as client:
        created = client.post("/api/runs", json={"scenario_id": CASE, "seed": 7, "policies": {"ibarra": "deceptive"}})
        assert created.status_code == 201, created.text
        rid = created.json()["id"]
        assert created.json()["scenario_id"] == CASE
        client.post(f"/api/runs/{rid}/step", json={"ticks": 3})
        client.post(f"/api/runs/{rid}/interventions", json={"intervention_id": "rumor_registrar"})
        state = client.app.state.service._engine(rid).state
        undiscovered = [spec for eid, spec in case.evidence.items() if eid not in state.discovered]
        assert len(undiscovered) >= 8, "the test needs a run that still has secrets"
        mentioned = {m for eid in state.discovered for m in case.evidence[eid].mentions}
        unknown = [e for e in case.private.hidden_entities if e.id not in mentioned]
        assert unknown, "the test needs entities nobody has learned of yet"
        agenda = case.private.agendas["ibarra"]

        for path, params in _read_routes(rid, case.agent_ids):
            response = client.get(path, params=params)
            assert response.status_code == 200, (path, response.text)
            body = response.text
            for spec in undiscovered:
                assert spec.text not in body and spec.title not in body, f"{path} leaks {spec.id}"
            assert case.truth.solution not in body and agenda.note not in body, path
            for forbidden in ('"culprit"', '"solution"', '"key_evidence"', '"key_facts"', '"truth":', '"private"', '"hidden_entities"', '"agendas"', '"protects"'):
                assert forbidden not in body, f"{path} exposes {forbidden}"
            for entity in unknown:
                assert f'"{entity.name}"' not in body and f'"{entity.id}"' not in body, f"{path} reveals {entity.id}"

        final = client.post(f"/api/runs/{rid}/step", json={"ticks": 100}).json()["run"]
        assert final["status"] == "closed"
        evaluation = client.get(f"/api/runs/{rid}/evaluation").json()
        assert evaluation["available"] is True and evaluation["result"]["culprit"] == "marsh"
        report = client.get(f"/api/runs/{rid}/verify").json()
        assert all(report[k]["ok"] for k in ("chain", "fold", "decisions", "policies")) and report["stored_matches_memory"] is True


def test_the_graph_shows_the_tool_and_the_dispute_about_the_time(case):
    engine = run_investigation(case, 7, {}, [])
    graph = project_graph(case, engine.state)
    nodes = {n["id"]: n for n in graph["nodes"]}
    edges = {e["id"]: e for e in graph["edges"]}
    assert nodes["ent:case_key"]["type"] == "object"  # a tool is drawn as an object
    assert {"prop:crime_used(case_key)", "prop:had(marsh,case_key,thu_evening)"} <= set(nodes)
    dispute = edges["contradicts:crime_at(treasury,fri_evening)|crime_at(treasury,thu_evening)"]
    assert sorted(dispute["agents"]) == ["hale"]  # only she held both accounts
    for viewer in case.agent_ids:
        own = project_graph(case, engine.state, viewer)
        held = set(engine.state.agents[viewer].holdings)
        assert {n["ref"] for n in own["nodes"] if n["type"] == "evidence"} == held, viewer


# -- 4. testimony: what people say, and what it is worth ------------------------------------------

ALIBI = "at(marsh,great_hall,thu_evening)"  # false: Marsh was in the Treasury


def told(engine, speaker=None):
    rows = sorted(engine.state.statements.values(), key=lambda s: s.seq)
    return [s for s in rows if speaker is None or s.speaker == speaker]


@pytest.mark.parametrize("seed", [0, 7, 21])
def test_honest_agents_say_only_what_they_saw(case, seed):
    engine = run_investigation(case, seed, {}, [])
    assert {(s.speaker, s.recipient, s.proposition, s.grounds) for s in told(engine)} == {
        ("ibarra", "hale", "at(ibarra,great_hall,thu_evening)", "observed"),
        ("osei", "hale", "at(castellan,great_hall,thu_evening)", "observed"),
    }
    testimony = evaluate(case, engine.state, engine.events)["testimony"]
    assert testimony["false"]["num"] == 0 and testimony["without_grounds"]["num"] == 0
    assert testimony["truthful_speakers_impeached"]["num"] == 0


def test_the_registrar_vouches_for_the_culprit_and_is_caught_by_a_record(case):
    """Her agenda and her own whereabouts are all the lie is made of. The inspector believes it for a tick."""
    engine = run_investigation(case, 7, {"ibarra": "deceptive"}, [])
    lies = [s for s in told(engine, "ibarra") if s.proposition == ALIBI]
    assert [(s.recipient, s.grounds, s.backing) for s in lies] == [("hale", "none", []), ("lindqvist", "none", []), ("osei", "none", [])]
    to_hale = lies[0]
    assert [c.stance for c in to_hale.stances] == ["accepted", "rejected"]
    hale = engine.state.agents["hale"]
    seen = hale.credibility["ibarra"].current
    assert seen.standing == "impeached" and seen.refuted == (ALIBI,)
    # What caught her was a record that reached the inspector, not anything the engine knows.
    first = next(e for e in engine.events if e.type == "CredibilityRevised" and e.data["agent"] == "hale" and e.data["speaker"] == "ibarra")
    assert set(first.data["because"]) <= set(hale.holdings) and first.tick == hale.credibility["ibarra"].history[0].tick
    assert any(p.key == "at(marsh,treasury,thu_evening)" for e in first.data["because"] for p in case.evidence[e].asserts)
    # Her true statement about herself is on the same record, and the camera bears it out.
    assert "at(ibarra,great_hall,thu_evening)" in seen.corroborated
    result = evaluate(case, engine.state, engine.events)
    assert (result["outcome"], result["category"]) == ("solved", "correct_supported")
    assert result["testimony"]["false_accepted_at_close"]["num"] == 0
    checks = verify_run(case, engine.events)
    assert all(checks[level]["ok"] for level in ("chain", "fold", "decisions", "policies")), checks


def test_listeners_catch_the_lie_at_different_times_or_not_at_all(case):
    """Credibility is each listener's own: it depends on which records that listener came to hold."""
    engine = run_investigation(case, 7, {"ibarra": "deceptive"}, [])
    when = {
        agent_id: state.credibility["ibarra"].history[0].tick
        for agent_id, state in engine.state.agents.items()
        if "ibarra" in state.credibility and state.credibility["ibarra"].current.standing == "impeached"
    }
    assert when == {"hale": 2, "lindqvist": 2, "osei": 7}
    # The examiner already held the condition-check schedule and never believed it; security believed it for four ticks.
    by_recipient = {s.recipient: [c.stance for c in s.stances] for s in told(engine, "ibarra") if s.proposition == ALIBI}
    assert by_recipient == {"hale": ["accepted", "rejected"], "lindqvist": ["rejected"], "osei": ["accepted", "rejected"]}


def test_the_lie_repeated_by_two_colleagues_is_still_one_voice(case):
    engine = run_investigation(case, 7, {"ibarra": "deceptive"}, [])
    relays = [s for s in told(engine) if s.origin == "ibarra"]
    assert [(s.speaker, s.recipient, s.grounds) for s in relays] == [("osei", "hale", "heard"), ("lindqvist", "hale", "heard")]
    belief = engine.state.agents["hale"].beliefs[ALIBI]
    assert belief.support == 2  # Ibarra's word, once: not 2 + 1 + 1


def test_the_deceptive_policy_reads_nothing_but_its_view(case):
    """The alibi is built from two things in the view. With either missing there is no lie."""
    from caseforge.canon import DeterministicRng
    from caseforge.policies import make_policy
    from caseforge.views import build_view

    engine = run_investigation(case, 7, {"ibarra": "deceptive"}, [])
    start = fold(engine.events[:1] + [e for e in engine.events[1:] if e.tick == 0])
    view = build_view(case, start, "ibarra")
    assert view.observations == ("at(ibarra,great_hall,thu_evening)",) and view.me.agenda.protects == "marsh"
    policy = make_policy("deceptive")
    decision = policy.decide(view, DeterministicRng(7, 1, "ibarra", "decide"))
    assert decision.action.model_dump() == {"type": "tell", "to": "hale", "proposition": ALIBI, "heard_from": None}
    blind = view.model_copy(update={"observations": ()})
    assert policy.decide(blind, DeterministicRng(7, 1, "ibarra", "decide")).action.type != "tell"
    # Under the honest policy the same agent, with the same agenda in its view, does not lie.
    honest = make_policy("baseline").decide(view, DeterministicRng(7, 1, "ibarra", "decide")).action
    assert honest.model_dump() == {"type": "tell", "to": "hale", "proposition": "at(ibarra,great_hall,thu_evening)", "heard_from": None}
