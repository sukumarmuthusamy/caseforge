"""The optional LLM policy: off by default, strictly validated, never able to corrupt state.

No test here talks to a network. A fixture makes any attempt fail loudly.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request

import pytest

from caseforge.canon import DeterministicRng, canonical_json
from caseforge.engine import Engine, EngineError, verify_run
from caseforge.policies import make_policy
from caseforge.policies.base import legal_actions
from caseforge.policies.baseline import BaselinePolicy
from caseforge.policies.llm import PROCESS_BUDGET, CallBudget, LLMConfig, LLMDisabled, LLMPolicy, build_messages, parse_choice
from caseforge.service import RunService
from caseforge.store import Store
from caseforge.state import fold, state_fingerprint
from caseforge.views import build_view

from .conftest import SEED

CONFIG = LLMConfig(base_url="http://llm.invalid/v1", model="test-model", max_retries=2)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a test attempted a real network request")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    for name in ("CASEFORGE_LLM_ENABLED", "CASEFORGE_LLM_BASE_URL", "CASEFORGE_LLM_MODEL", "CASEFORGE_LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)


class FakeClient:
    """Returns scripted replies in order, repeating the last one. Records every call."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = 0

    def complete(self, messages, config):
        self.calls += 1
        reply = self.replies[min(self.calls - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, dict) else {"text": reply, "usage": {"prompt_tokens": 100, "completion_tokens": 9}}


def factory_with(policy):
    return lambda name: policy if name == "llm" else make_policy(name)


def test_llm_is_off_unless_explicitly_enabled(scenario, monkeypatch):
    with pytest.raises(LLMDisabled):
        make_policy("llm")
    with pytest.raises(EngineError, match="not available"):
        Engine.start(scenario, SEED, {"okafor": "llm"})
    monkeypatch.setenv("CASEFORGE_LLM_ENABLED", "1")
    with pytest.raises(LLMDisabled, match="BASE_URL"):
        make_policy("llm")  # opting in without naming an endpoint is still refused


def test_enabled_configuration_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("CASEFORGE_LLM_ENABLED", "1")
    monkeypatch.setenv("CASEFORGE_LLM_BASE_URL", "http://localhost:11434/v1/")
    monkeypatch.setenv("CASEFORGE_LLM_MODEL", "local-model")
    policy = make_policy("llm")  # building it must not contact anything
    assert policy.config.base_url == "http://localhost:11434/v1" and policy.config.api_key is None
    assert policy.deterministic is False


@pytest.mark.parametrize("text,fragment", [
    ("I think the detective should accuse Brandt.", "no JSON object"),
    ('{"choice": 1,, }', "invalid JSON"),
    ('{"choice": "1"}', "schema violation"),
    ('{"choice": 1.5}', "schema violation"),
    ('{"choice": true}', "schema violation"),
    ('{"choice": 1, "action": {"type": "accuse", "suspect": "brandt"}}', "schema violation"),
    ('{"rationale": "no choice given"}', "schema violation"),
    ('{"choice": 99}', "outside the menu"),
    ('{"choice": -1}', "outside the menu"),
    ('{"choice": 0, "rationale": "' + "x" * 700 + '"}', "schema violation"),
])
def test_invalid_model_replies_are_rejected(text, fragment):
    with pytest.raises(ValueError, match=fragment):
        parse_choice(text, 5)


def test_valid_reply_may_be_wrapped_in_prose_or_fences():
    parsed = parse_choice('Sure.\n```json\n{"choice": 3, "rationale": "E01 names the card"}\n```', 5)
    assert parsed.choice == 3 and parsed.rationale == "E01 names the card"


def test_valid_reply_selects_from_the_menu_and_is_recorded(scenario, fresh):
    view = build_view(scenario, fresh.state, "okafor")
    menu = legal_actions(view)
    client = FakeClient('{"choice": 2, "rationale": "start at the scene"}')
    decision = LLMPolicy(client, CONFIG).decide(view, DeterministicRng(SEED, 1, "okafor"))
    assert decision.action == menu[2]
    assert decision.trace.reason == "start at the scene"
    record = decision.trace.llm
    assert record["model"] == "test-model" and record["choice"] == 2 and record["fallback"] is False
    assert record["attempts"] == [{"ok": True}] and len(record["prompt_sha256"]) == 64
    assert record["usage"] == {"prompt_tokens": 100, "completion_tokens": 9}
    assert client.calls == 1


def test_garbage_replies_fall_back_to_baseline_after_bounded_retries(scenario, fresh):
    view = build_view(scenario, fresh.state, "okafor")
    client = FakeClient("no json here", '{"choice": 9999}', '{"choice": "two"}', '{"choice": 0}')
    decision = LLMPolicy(client, CONFIG).decide(view, DeterministicRng(SEED, 1, "okafor"))
    assert client.calls == 1 + CONFIG.max_retries  # the fourth, valid reply is never requested
    expected = BaselinePolicy().decide(view, DeterministicRng(SEED, 1, "okafor"))
    assert decision.action == expected.action
    assert decision.trace.llm["fallback"] is True
    assert [a["error"].split(":")[0] for a in decision.trace.llm["attempts"]] == ["no JSON object in reply", "choice 9999 is outside the menu (0..%d)" % (decision.trace.llm["menu_size"] - 1), "schema violation at choice"]


def test_transport_errors_fall_back_without_leaking_details(scenario, fresh):
    view = build_view(scenario, fresh.state, "okafor")
    client = FakeClient(urllib.error.URLError("connection refused to http://llm.invalid/v1?key=SECRET"))
    decision = LLMPolicy(client, CONFIG).decide(view, DeterministicRng(SEED, 1, "okafor"))
    assert decision.trace.llm["fallback"] is True
    assert all(a == {"error": "transport: URLError"} for a in decision.trace.llm["attempts"])
    assert "SECRET" not in canonical_json(decision.model_dump(mode="json"))


def test_call_budget_is_enforced(scenario, fresh):
    view = build_view(scenario, fresh.state, "okafor")
    client = FakeClient('{"choice": 0}')
    policy = LLMPolicy(client, LLMConfig(base_url="http://llm.invalid/v1", model="m", max_calls=2))
    for _ in range(5):
        policy.decide(view, DeterministicRng(SEED, 1, "okafor"))
    assert client.calls == 2
    last = policy.decide(view, DeterministicRng(SEED, 1, "okafor"))
    assert last.trace.llm["fallback"] is True and last.trace.llm["attempts"] == [{"error": "call budget exhausted"}]


class WaitingClient(FakeClient):
    """Always picks the last menu entry, which is `wait`: a run driven by it stays open."""

    def complete(self, messages, config):
        self.calls += 1
        menu = messages[-1]["content"].split("Menu:")[1].split("Reply with JSON only.")[0]
        return {"text": '{"choice": %d}' % (len(menu.strip().splitlines()) - 1), "usage": None}


def fresh_policy_factory(client, config):
    """Like the real registry: every engine that asks gets a *new* policy instance."""
    return lambda name: LLMPolicy(client, config) if name == "llm" else make_policy(name)


def test_budget_is_shared_by_every_engine_in_the_process(scenario):
    """A second engine must not start with a fresh allowance."""
    client = WaitingClient()
    config = LLMConfig(base_url="http://llm.invalid/v1", model="m", max_calls=1, max_retries=0)
    for _ in range(2):
        engine = Engine.start(scenario, SEED, {"okafor": "llm"}, fresh_policy_factory(client, config))
        engine.step()
    assert client.calls == 1
    assert PROCESS_BUDGET.spent == 1
    decided = [e for e in engine.events if e.type == "ActionTaken" and e.data["trace"]["policy"] == "llm"]
    assert decided[-1].data["trace"]["llm"]["attempts"] == [{"error": "call budget exhausted"}]


def test_budget_survives_new_runs_branches_and_engine_reloads(tmp_path, monkeypatch):
    """Creating a run, branching and a failed operation each rebuild the policy; none renews the budget."""
    client = WaitingClient()
    config = LLMConfig(base_url="http://llm.invalid/v1", model="m", max_calls=5, max_retries=0)
    service = RunService(Store(tmp_path / "budget.sqlite3"), fresh_policy_factory(client, config))

    first = service.create_run("missing_prototype", SEED, {"okafor": "llm"})
    service.step(first["id"], 2)  # calls 1 and 2
    branch = service.branch(first["id"], 1)
    service.step(branch["id"], 1)  # call 3: the branch has its own engine and policy instance
    second = service.create_run("missing_prototype", 11, {"nair": "llm"})
    service.step(second["id"], 1)  # call 4

    def broken(run_id, events, **kwargs):
        raise RuntimeError("disk on fire")

    real = service.store.append_events
    monkeypatch.setattr(service.store, "append_events", broken)
    with pytest.raises(RuntimeError):
        service.step(first["id"], 1)  # call 5: charged although the tick itself was discarded
    monkeypatch.setattr(service.store, "append_events", real)
    assert first["id"] not in service._engines  # the engine and its policy were thrown away
    assert client.calls == 5

    service.step(first["id"], 3)  # rebuilt engine, new policy instance, same budget
    service.step(second["id"], 3)
    service.step(branch["id"], 3)
    assert client.calls == 5 == PROCESS_BUDGET.spent


def test_retries_are_charged_to_the_budget(scenario, fresh):
    view = build_view(scenario, fresh.state, "okafor")
    client = FakeClient("not json")
    config = LLMConfig(base_url="http://llm.invalid/v1", model="m", max_calls=2, max_retries=5)
    decision = LLMPolicy(client, config).decide(view, DeterministicRng(SEED, 1, "okafor"))
    assert client.calls == 2
    assert decision.trace.llm["fallback"] is True
    assert decision.trace.llm["attempts"][-1] == {"error": "call budget exhausted"}


def test_an_explicit_budget_is_independent_of_the_process_budget(scenario, fresh):
    view = build_view(scenario, fresh.state, "okafor")
    client = FakeClient('{"choice": 0}')
    own = CallBudget()
    policy = LLMPolicy(client, LLMConfig(base_url="http://llm.invalid/v1", model="m", max_calls=1), budget=own)
    policy.decide(view, DeterministicRng(SEED, 1, "okafor"))
    policy.decide(view, DeterministicRng(SEED, 1, "okafor"))
    assert (client.calls, own.spent, PROCESS_BUDGET.spent) == (1, 1, 0)


def test_budget_never_overspends_under_concurrency():
    budget = CallBudget()
    granted = []
    barrier = threading.Barrier(16)

    def worker():
        barrier.wait()
        for _ in range(200):
            if budget.try_spend(250):
                granted.append(1)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(granted) == 250 == budget.spent


def test_prompt_contains_only_the_agents_own_view(scenario, solved):
    view = build_view(scenario, solved.state, "nair")
    prompt = canonical_json(build_messages(view, legal_actions(view)))
    held = set(solved.state.agents["nair"].holdings)
    for evidence_id, spec in scenario.evidence.items():
        if evidence_id not in held:
            assert spec.text[:40] not in prompt
    assert scenario.truth.solution[:40] not in prompt


class MostlyBrokenClient(FakeClient):
    """Cycles through bad replies; every fifth reply is valid and picks the last menu entry (wait)."""

    BAD = ["nonsense", '{"choice": 100000}', '{"choice": 1, "extra": 1}', '{"choice": "x"}']

    def __init__(self):
        super().__init__()

    def complete(self, messages, config):
        self.calls += 1
        if self.calls % 5:
            return {"text": self.BAD[self.calls % 4], "usage": None}
        menu = messages[-1]["content"].split("Menu:")[1].split("Reply with JSON only.")[0]
        last = len(menu.strip().splitlines()) - 1
        return {"text": '{"choice": %d, "rationale": "pause"}' % last, "usage": {"prompt_tokens": 5, "cost": 0.0001}}


def test_run_with_misbehaving_model_stays_consistent_and_replayable(scenario):
    client = MostlyBrokenClient()
    policy = LLMPolicy(client, CONFIG)
    engine = Engine.start(scenario, SEED, {"okafor": "llm", "nair": "llm"}, factory_with(policy))
    engine.run(6)
    assert engine.state.tick == 6
    assert state_fingerprint(fold(engine.events)) == state_fingerprint(engine.state)

    decisions = [e for e in engine.events if e.type in ("ActionTaken", "ActionRejected") and e.data["trace"]["policy"] == "llm"]
    assert len(decisions) == 12
    assert any(e.data["trace"]["llm"]["fallback"] for e in decisions)
    assert any(not e.data["trace"]["llm"]["fallback"] for e in decisions)
    for event in decisions:
        usage = event.data["trace"]["llm"].get("usage")
        assert usage is None or all(isinstance(v, int) for v in usage.values())

    # Replay uses the recorded decisions and must not consult the model again.
    calls_before = client.calls
    report = verify_run(scenario, engine.events, factory_with(policy))
    assert report["chain"]["ok"] and report["fold"]["ok"]
    assert report["decisions"]["ok"] is True
    assert report["policies"]["ok"] is None and "non-deterministic" in report["policies"]["detail"]
    assert client.calls == calls_before


def test_model_choosing_an_illegal_moment_is_stopped_by_the_engine(scenario):
    """The menu offers 'accuse' for every suspect. Picking it blindly is legal but scored as what it is."""
    view_engine = Engine.start(scenario, SEED)
    menu = legal_actions(build_view(scenario, view_engine.state, "okafor"))
    accuse_index = next(i for i, a in enumerate(menu) if a.type == "accuse" and a.suspect == "mercer")
    policy = LLMPolicy(FakeClient('{"choice": %d, "rationale": "a hunch"}' % accuse_index), CONFIG)
    engine = Engine.start(scenario, SEED, {"okafor": "llm"}, factory_with(policy))
    engine.run()
    assert engine.state.status == "closed" and engine.state.accusation["suspect"] == "mercer"
    from caseforge.evaluation import evaluate

    result = evaluate(scenario, engine.state, engine.events)
    assert result["outcome"] == "wrong_accusation" and result["accusation_supported"] is False
