"""Spoken statements and speaker credibility, played by fixed scripts in the tiny case.

Every expected value is worked out by hand from the published weights and is
written beside the reason. Nothing expected here is computed by the reasoner.

The world (see test_tiny_case.py): Bob took the gem from the vault on Monday
night (s1). Ann was in the cafe. Two things are changed for these tests: the
yard gate entry that places Bob at the vault (T4, a record) is filed at the
bank where the detective can find it herself, and the clerk, Cole, saw Ann in
the cafe with his own eyes.

Cole is not a suspect, so his word weighs 2. A record weighs 4. Believed means
a net of 2.
"""

from __future__ import annotations

import pytest

from caseforge.engine import Engine, IncompatibleRun, branch_prefix, verify_run
from caseforge.evaluation import evaluate
from caseforge.graph import project_graph
from caseforge.models import Inspect, Tell
from caseforge.observer import snapshot
from caseforge.state import fold, state_fingerprint
from caseforge.views import build_view

from .conftest import ScriptedPolicy, all_scripted, scripted_factory
from .test_replay import rehashed
from .test_tiny_case import build

LIE = "at(bob,cafe,s1)"  # false: Bob was at the vault
SEEN = "at(ann,cafe,s1)"  # true, and Cole saw it
VAULT = "at(bob,vault,s1)"  # true


def talkative(data):
    record = next(e for e in data["private"]["evidence"] if e["id"] == "T4")
    record.update(source="bank", shareable=True)
    data["private"]["observations"] = {"cole": [SEEN]}


THE_LIE = {
    (1, "cole"): Tell(to="dee", proposition=LIE),
    (2, "cole"): Tell(to="dee", proposition=SEEN),
    (3, "cole"): Tell(to="pia", proposition=LIE),
    (4, "dee"): Inspect(source="bank", topic="bob"),  # finds T4 (Bob at the vault) and T5 (his overdraft)
    (5, "pia"): Tell(to="dee", proposition=LIE, heard_from="cole"),
}


def play(scenario, script, ticks=None) -> Engine:
    engine = Engine.start(scenario, 1, all_scripted(scenario), policy_factory=scripted_factory(ScriptedPolicy(script)))
    engine.run(ticks)
    return engine


@pytest.fixture(scope="module")
def world():
    return build(talkative)


@pytest.fixture(scope="module")
def lied(world) -> Engine:
    return play(world, THE_LIE)


def statements(engine: Engine):
    return sorted(engine.state.statements.values(), key=lambda s: s.seq)


def stances(statement):
    return [(c.stance, c.belief, c.tick) for c in statement.stances]


# -- what is recorded ----------------------------------------------------------------------------


def test_a_statement_records_who_said_what_to_whom_and_on_what_grounds(lied):
    lie, seen, to_pia, relay = statements(lied)
    assert (lie.speaker, lie.recipient, lie.proposition, lie.origin, lie.grounds, lie.backing) == ("cole", "dee", LIE, None, "none", [])
    assert (seen.speaker, seen.recipient, seen.proposition, seen.grounds) == ("cole", "dee", SEEN, "observed")
    assert (to_pia.speaker, to_pia.recipient, to_pia.grounds) == ("cole", "pia", "none")
    # Pia passes it on as Cole's word, and the log says which statement she is passing on.
    assert (relay.speaker, relay.recipient, relay.origin, relay.relays, relay.grounds, relay.backing) == ("pia", "dee", "cole", to_pia.id, "heard", [to_pia.id])
    made = [e for e in lied.events if e.type == "StatementMade"]
    assert [e.data["statement"] for e in made] == [f"S{e.seq}" for e in made]  # the id is the event's own position
    assert [e.actor for e in made] == ["cole", "cole", "cole", "pia"]
    assert [e.data["code"] for e in lied.events if e.type == "ActionRejected"] == []


def test_a_statement_backed_by_a_record_names_the_record(world):
    script = {
        (1, "cole"): Tell(to="dee", proposition=LIE),
        (2, "pia"): Tell(to="dee", proposition=VAULT),  # true, and she has nothing for it
        (3, "dee"): Inspect(source="bank", topic="bob"),
        (4, "dee"): Tell(to="pia", proposition=VAULT),
    }
    engine = play(world, script, ticks=4)
    by_cole, by_pia, by_dee = statements(engine)
    assert (by_pia.grounds, by_pia.backing) == ("none", [])
    assert (by_dee.grounds, by_dee.backing) == ("held", ["T4"])


# -- truthful, false, contradictory ---------------------------------------------------------------


def test_a_truthful_statement_is_believed_on_the_speakers_word(world):
    engine = play(world, THE_LIE, ticks=2)
    dee = engine.state.agents["dee"]
    belief = dee.beliefs[SEEN]
    assert (belief.support, belief.contra, belief.status) == (2, 0, "believed")
    seen = statements(engine)[1]
    assert belief.evidence == (seen.id,) and stances(seen) == [("accepted", "believed", 2)]
    # Testimony is not a verified fact: nothing was checked, so nothing is known about the speaker.
    assert dee.credibility == {}


def test_a_false_statement_is_believed_until_a_record_contradicts_it(lied):
    """Tick 1: Cole's word, 2 against nothing. Tick 4: the gate entry, 4 against his 2, a net of -2."""
    lie = statements(lied)[0]
    assert stances(lie) == [("accepted", "believed", 1), ("rejected", "rejected", 4)]
    dee = lied.state.agents["dee"]
    assert (dee.beliefs[LIE].support, dee.beliefs[LIE].contra, dee.beliefs[LIE].status) == (2, 4, "rejected")
    assert (dee.beliefs[VAULT].support, dee.beliefs[VAULT].contra, dee.beliefs[VAULT].status) == (4, 2, "believed")
    # The contradiction stays on the record after it is resolved.
    assert dee.contradictions == [f"{LIE}|{VAULT}"]


def test_the_engine_never_checks_a_statement_against_the_truth(world, lied):
    """The lie went through validation like any other statement, and its recipient was not told it was baseless."""
    taken = [e for e in lied.events if e.type == "ActionTaken" and e.data["action"]["type"] == "tell"]
    assert len(taken) == 4
    view = build_view(world, lied.state, "dee")
    assert [(s.speaker, s.proposition, s.origin) for s in view.statements] == [("cole", LIE, None), ("cole", SEEN, None), ("pia", LIE, "cole")]
    assert not hasattr(view.statements[0], "grounds")
    assert '"grounds"' not in view.model_dump_json() and '"backing"' not in view.model_dump_json()


def test_two_people_who_disagree_leave_the_listener_undecided(world):
    """Cole says the cafe, Pia says the vault: 2 against 2. Neither is believed, neither is caught out."""
    script = {
        (1, "cole"): Tell(to="dee", proposition=LIE),
        (2, "pia"): Tell(to="dee", proposition=VAULT),
    }
    engine = play(world, script, ticks=2)
    dee = engine.state.agents["dee"]
    assert {key: (b.support, b.contra, b.status) for key, b in dee.beliefs.items() if key in (LIE, VAULT)} == {
        LIE: (2, 2, "disputed"), VAULT: (2, 2, "disputed"),
    }
    assert dee.contradictions == [f"{LIE}|{VAULT}"]
    by_cole, by_pia = statements(engine)
    assert stances(by_cole) == [("accepted", "believed", 1), ("questioned", "disputed", 2)]
    assert stances(by_pia) == [("questioned", "disputed", 2)]
    assert dee.credibility == {}  # one person's word never impeaches another's


# -- credibility ----------------------------------------------------------------------------------


def test_a_speaker_caught_out_is_impeached_and_their_other_word_counts_for_less(lied):
    """The record refutes one claim. Cole's other claim, which is true, drops from 2 to 1: no longer believed."""
    dee = lied.state.agents["dee"]
    seen = dee.credibility["cole"]
    assert (seen.current.standing, seen.current.refuted, seen.current.corroborated) == ("impeached", (LIE,), ())
    assert [(h.standing, h.tick) for h in seen.history] == [("impeached", 4)]
    assert (dee.beliefs[SEEN].support, dee.beliefs[SEEN].status) == (1, "tentative")
    assert stances(statements(lied)[1]) == [("accepted", "believed", 2), ("questioned", "tentative", 4)]
    event = next(e for e in lied.events if e.type == "CredibilityRevised")
    assert event.data == {
        "agent": "dee", "speaker": "cole", "before": None, "because": ["T4", "T5"],
        "credibility": {"standing": "impeached", "refuted": [LIE], "corroborated": []},
    }
    # It is recorded as a consequence of the search that found the record.
    assert lied.events[event.cause].data["action"] == {"type": "inspect", "source": "bank", "topic": "bob"}


def test_credibility_belongs_to_the_listener(lied):
    """Pia heard the same lie and holds no record against it: she still believes it, and still trusts Cole."""
    pia = lied.state.agents["pia"]
    assert pia.beliefs[LIE].status == "believed" and pia.credibility == {}
    assert stances(statements(lied)[2]) == [("accepted", "believed", 3)]
    assert lied.state.agents["dee"].credibility["cole"].current.standing == "impeached"


def test_each_agent_sees_only_its_own_side(world, lied):
    dee, pia, cole = (build_view(world, lied.state, a) for a in ("dee", "pia", "cole"))
    assert set(dee.credibility) == {"cole"} and dee.credibility["cole"].standing == "impeached"
    assert pia.credibility == {} and cole.credibility == {}
    assert cole.observations == (SEEN,) and dee.observations == () and pia.observations == ()
    # Pia was not party to what Cole told Dee.
    assert [(s.speaker, s.recipient, s.mine) for s in pia.statements] == [("cole", "pia", False), ("pia", "dee", True)]
    # Cole is not told that he was found out.
    assert "impeached" not in cole.model_dump_json()


def test_a_repeated_statement_is_not_corroboration(lied):
    """Dee hears Cole's claim from Cole and again through Pia. It is one voice: the support stays at 2."""
    dee = lied.state.agents["dee"]
    lie, _, _, relay = statements(lied)
    assert dee.beliefs[LIE].support == 2
    assert set(dee.beliefs[LIE].evidence) == {lie.id, relay.id}  # both are on the record as the reason
    assert stances(relay) == [("rejected", "rejected", 5)]
    # The revision that followed added the second statement as a reason and changed no weight and no status.
    revision = next(e for e in lied.events if e.type == "BeliefsRevised" and e.tick == 5)
    assert list(revision.data["changes"]) == [LIE, VAULT]  # the same statement is also listed against the vault
    assert (revision.data["changes"][VAULT]["support"], revision.data["changes"][VAULT]["contra"], revision.data["changes"][VAULT]["status"]) == (4, 2, "believed")
    assert (revision.data["changes"][LIE]["support"], revision.data["changes"][LIE]["contra"], revision.data["changes"][LIE]["status"]) == (2, 4, "rejected")


def test_passed_on_alone_it_weighs_as_hearsay(world):
    """Dee never hears Cole himself, only Pia's report of him: weight 1, not believed."""
    script = {
        (1, "cole"): Tell(to="pia", proposition=LIE),
        (2, "pia"): Tell(to="dee", proposition=LIE, heard_from="cole"),
    }
    engine = play(world, script, ticks=2)
    belief = engine.state.agents["dee"].beliefs[LIE]
    assert (belief.support, belief.status) == (1, "tentative")
    assert stances(statements(engine)[1]) == [("questioned", "tentative", 2)]


# -- history --------------------------------------------------------------------------------------


def test_what_was_believed_earlier_is_not_rewritten(lied):
    """At tick 3 Dee believed the lie and had nothing against Cole. Rebuilding that tick still says so."""
    then = fold([e for e in lied.events if e.tick <= 3])
    assert then.agents["dee"].beliefs[LIE].status == "believed"
    assert then.agents["dee"].credibility == {}
    lie = sorted(then.statements.values(), key=lambda s: s.seq)[0]
    assert stances(lie) == [("accepted", "believed", 1)]
    stamp = lied.state.agents["dee"].belief_stamps[LIE]
    assert stamp.first.tick == 1 and stamp.last.tick == 5  # held since tick 1; last touched when Pia repeated it


# -- what the engine refuses ----------------------------------------------------------------------


def test_an_agent_cannot_speak_of_what_it_has_never_come_across():
    """Without the observation Cole has no way to know the cafe exists, so he cannot place anyone there."""
    scenario = build()
    script = {
        (1, "cole"): Tell(to="dee", proposition=SEEN),  # the cafe is a hidden entity
        (2, "cole"): Tell(to="dee", proposition="took(bob,gem)"),  # guilt is not something to state on one's word
        (3, "cole"): Tell(to="dee", proposition="at(bob,vault,s9)"),  # no such time
        (4, "cole"): Tell(to="dee", proposition=VAULT, heard_from="pia"),  # Pia never said so
        (5, "cole"): Tell(to="cole", proposition=VAULT),
        (6, "cole"): Tell(to="dee", proposition="nonsense"),
        (7, "cole"): Tell(to="dee", proposition=VAULT),  # allowed: he knows Bob and the vault
        (8, "cole"): Tell(to="dee", proposition=VAULT),  # but not twice
    }
    engine = play(scenario, script, ticks=8)
    assert [e.data["code"] for e in engine.events if e.type == "ActionRejected"] == [
        "unknown_topic", "not_tellable", "malformed_proposition", "not_heard", "unknown_agent", "malformed_proposition", "already_told",
    ]
    assert len(engine.state.statements) == 1
    assert not any(e.type in ("StatementMade", "StatementWeighed") and e.tick < 7 for e in engine.events)


def test_a_view_carries_no_truth_and_nobody_elses_observation(world, lied):
    for agent_id in ("dee", "pia"):
        body = build_view(world, lied.state, agent_id).model_dump_json()
        assert '"observations":[]' in body and "truth" not in body and "culprit" not in body
    # The observer of an open run sees what was said and what the speaker had for it, never whether it was so.
    observed = snapshot(world, lied.state)
    assert [(s["speaker"], s["recipient"], s["grounds"], s["stance"]) for s in observed["statements"]] == [
        ("cole", "dee", "none", "rejected"), ("cole", "dee", "observed", "questioned"), ("cole", "pia", "none", "accepted"), ("pia", "dee", "heard", "rejected"),
    ]
    assert all("true" not in s for s in observed["statements"])


# -- replay and branching -------------------------------------------------------------------------


def test_a_run_with_statements_replays_exactly(world, lied):
    factory = scripted_factory(ScriptedPolicy(THE_LIE))
    checks = verify_run(world, lied.events, factory)
    assert all(checks[level]["ok"] for level in ("chain", "fold", "decisions", "policies")), checks
    assert state_fingerprint(fold(lied.events)) == state_fingerprint(lied.state)
    again = play(world, THE_LIE)
    assert [e.hash for e in again.events] == [e.hash for e in lied.events]


def test_a_branch_taken_before_the_lie_is_caught_can_go_another_way(world, lied):
    prefix = branch_prefix(lied.events, 3)
    same = Engine(world, prefix, scripted_factory(ScriptedPolicy(THE_LIE)))
    same.run()
    assert [e.hash for e in same.events] == [e.hash for e in lied.events]

    # In the other branch the detective never looks at the bank, so the lie stands.
    other = Engine(world, prefix, scripted_factory(ScriptedPolicy({})))
    other.run()
    assert other.state.agents["dee"].beliefs[LIE].status == "believed" and other.state.agents["dee"].credibility == {}
    assert lied.state.agents["dee"].beliefs[LIE].status == "rejected"  # the parent is untouched


def test_a_log_from_the_engine_before_testimony_is_refused(world, lied):
    """Version 2 recorded no credibility: replaying such a run with this build would give a different log."""
    old = rehashed(lied.events[:10], lambda data: data.update(engine_version="2"))
    with pytest.raises(IncompatibleRun, match="engine version '2'"):
        Engine(world, old)


# -- evaluation -----------------------------------------------------------------------------------


def test_evaluation_counts_false_statements_and_who_saw_through_them(world, lied):
    """Four statements: the lie to Dee, the truth to Dee, the lie to Pia, and Pia passing the lie on.

    Three are false. Dee accepted the first until tick 4 and rejected the
    passed-on copy on arrival; Pia still accepts hers when the run ends.
    """
    result = evaluate(world, lied.state, lied.events)
    assert (result["outcome"], result["category"]) == ("unresolved", "unresolved")
    t = result["testimony"]
    assert (t["statements"], t["first_hand"], t["passed_on"]) == (4, 3, 1)
    assert t["without_grounds"] == {"num": 2, "den": 3, "pct": 67}
    assert t["false"] == {"num": 3, "den": 4, "pct": 75}
    assert t["false_ever_accepted"] == {"num": 2, "den": 3, "pct": 67}
    assert t["false_accepted_at_close"] == {"num": 1, "den": 3, "pct": 33}
    assert t["false_rejected_at_close"] == {"num": 2, "den": 3, "pct": 67}
    assert t["true_rejected_at_close"] == {"num": 0, "den": 1, "pct": 0}
    # Two listeners were told something false by Cole; one of them came to doubt him.
    assert t["false_speakers_impeached"] == {"num": 1, "den": 2, "pct": 50}
    # Nobody heard only true things from anyone, so there is nothing to count here.
    assert t["truthful_speakers_impeached"] == {"num": 0, "den": 0, "pct": None}
    assert t["refuted_claims_false"] == {"num": 1, "den": 1, "pct": 100}
    assert t["corroborated_claims_true"] == {"num": 0, "den": 0, "pct": None}
    assert [(i["speaker"], i["recipient"], i["true"], i["first_stance"], i["final_stance"]) for i in t["items"]] == [
        ("cole", "dee", False, "accepted", "rejected"),
        ("cole", "dee", True, "accepted", "questioned"),
        ("cole", "pia", False, "accepted", "accepted"),
        ("pia", "dee", False, "rejected", "rejected"),
    ]


def test_speaking_more_earns_nothing(world):
    """A run with no statements and a run full of true ones report the same zeros for everything that is scored."""
    silent = evaluate(world, *(lambda e: (e.state, e.events))(play(world, {}, ticks=2)))["testimony"]
    chatty = play(world, {(1, "cole"): Tell(to="dee", proposition=SEEN), (2, "cole"): Tell(to="pia", proposition=SEEN)}, ticks=2)
    spoken = evaluate(world, chatty.state, chatty.events)["testimony"]
    for key in ("false", "false_ever_accepted", "false_accepted_at_close", "false_speakers_impeached"):
        assert silent[key]["num"] == spoken[key]["num"] == 0
    assert silent["statements"] == 0 and spoken["statements"] == 2


# -- graph ----------------------------------------------------------------------------------------


def test_the_graph_shows_statements_without_calling_them_true(world, lied):
    lie, seen, to_pia, relay = statements(lied)
    graph = project_graph(world, lied.state)
    nodes = {n["id"]: n for n in graph["nodes"]}
    edges = {e["id"]: e for e in graph["edges"]}
    node = nodes[f"st:{lie.id}"]
    assert (node["type"], node["by"], node["to"], node["grounds"], node["stance"], node["first_tick"]) == ("statement", "cole", "dee", "none", "rejected", 1)
    assert edges[f"reported:ent:cole>st:{lie.id}"]["label"] == "told"
    assert edges[f"reported:ent:pia>st:{relay.id}"]["label"] == "passed on"
    assert edges[f"addressed:st:{lie.id}>ent:dee"]["stance"] == "rejected" and edges[f"addressed:st:{lie.id}>ent:dee"]["changed_tick"] == 4
    assert edges[f"supports:st:{lie.id}>prop:{LIE}"]["kind"] == "testimony"
    assert f"relays:st:{relay.id}>st:{to_pia.id}" in edges
    assert edges[f"witnessed:ent:cole>prop:{SEEN}"]["label"] == "saw"
    doubt = edges["doubts:ent:dee>ent:cole"]
    assert (doubt["tick"], doubt["items"]) == (4, [LIE])
    assert "doubts:ent:pia>ent:cole" not in edges
    assert not any("true" in n for n in nodes.values())

    # Dee's own graph: she sees what she was told, not what the speaker had for it, and not what was said to Pia.
    mine = project_graph(world, lied.state, "dee")
    mine_nodes = {n["id"]: n for n in mine["nodes"]}
    assert f"st:{to_pia.id}" not in mine_nodes
    assert "grounds" not in mine_nodes[f"st:{lie.id}"] and mine_nodes[f"st:{lie.id}"]["stance"] == "rejected"
    assert not any(e["type"] == "witnessed" for e in mine["edges"])
    # Cole's own graph: he knows what he had for it, and does not see what Dee made of it.
    his = {n["id"]: n for n in project_graph(world, lied.state, "cole")["nodes"]}
    assert his[f"st:{lie.id}"]["grounds"] == "none" and "stance" not in his[f"st:{lie.id}"]

    # Time travel: at tick 3 nobody doubts anybody.
    earlier = project_graph(world, fold([e for e in lied.events if e.tick <= 3]))
    assert not any(e["type"] == "doubts" for e in earlier["edges"])


# -- one voice, two places in one zone --------------------------------------------------------


def test_saying_it_again_about_the_doorway_does_not_undo_being_caught_out():
    """A counterexample found in review, as played.

    Dee holds the gate record T4 (Bob at the vault, 4). The cafe has a door,
    in the same zone. Tick 1: Cole says Bob was in the cafe (2). Rejected, and
    Cole is impeached. Tick 2: Cole says Bob was at the cafe door. It is the
    same man saying the same thing: still 2 against 4, still rejected, still
    impeached. Both statements stay on the record.
    """
    def aliases(data):
        talkative(data)
        data["public"]["entities"].append({"id": "cafe_door", "kind": "location", "name": "Cafe door", "zone": "cafe"})
        data["private"]["initial_holdings"] = {"dee": ["T4"]}

    from caseforge.scenario import lint

    scenario = build(aliases)
    assert lint(scenario) == []
    door = "at(bob,cafe_door,s1)"
    engine = play(scenario, {(1, "cole"): Tell(to="dee", proposition=LIE), (2, "cole"): Tell(to="dee", proposition=door)}, ticks=2)
    assert [e.data["code"] for e in engine.events if e.type == "ActionRejected"] == []

    def at_tick(tick):
        dee = fold([e for e in engine.events if e.tick <= tick]).agents["dee"]
        seen = dee.credibility["cole"].current
        return {k: (b.support, b.contra, b.status) for k, b in dee.beliefs.items() if k.startswith("at(bob,")}, seen.standing if seen else None, seen.refuted if seen else None

    assert at_tick(1) == ({LIE: (2, 4, "rejected"), VAULT: (4, 2, "believed")}, "impeached", (LIE,))
    assert at_tick(2) == ({LIE: (2, 4, "rejected"), door: (2, 4, "rejected"), VAULT: (4, 2, "believed")}, "impeached", (LIE, door))
    first, second = statements(engine)
    assert (first.proposition, second.proposition) == (LIE, door)
    assert stances(first) == [("rejected", "rejected", 1)] and stances(second) == [("rejected", "rejected", 2)]
