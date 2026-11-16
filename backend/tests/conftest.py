from __future__ import annotations

from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from caseforge.canon import DeterministicRng
from caseforge.engine import Engine
from caseforge.models import AgentView, Decision, DecisionTrace, Wait
from caseforge.policies import make_policy
from caseforge.policies.llm import PROCESS_BUDGET
from caseforge.scenario import Scenario, load_bundled

class LocalClient(TestClient):
    """The test client, talking to the loopback name the API answers to (Starlette's default, `testserver`, is refused)."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("base_url", "http://127.0.0.1")
        super().__init__(*args, **kwargs)


SCENARIO_ID = "missing_prototype"
SEED = 7


class ScriptedPolicy:
    """Test double: plays a fixed script keyed by (tick, agent); waits otherwise."""

    name = "scripted"
    deterministic = True

    def __init__(self, script: dict[tuple[int, str], Any] | None = None, on_decide: Callable[[AgentView], None] | None = None) -> None:
        self.script = script or {}
        self.on_decide = on_decide
        self.views: list[AgentView] = []

    def decide(self, view: AgentView, rng: DeterministicRng) -> Decision:
        self.views.append(view)
        if self.on_decide:
            self.on_decide(view)
        action = self.script.get((view.tick, view.me.id), Wait())
        if callable(action):  # lets a script react to ids it cannot know in advance
            action = action(view)
        return Decision(action=action, trace=DecisionTrace(policy=self.name, reason="scripted"))


def scripted_factory(policy: ScriptedPolicy):
    def factory(name: str):
        return policy if name == "scripted" else make_policy(name)

    return factory


def all_scripted(scenario: Scenario) -> dict[str, str]:
    return {agent: "scripted" for agent in scenario.agent_ids}


@pytest.fixture(autouse=True)
def fresh_call_budget():
    """The model-call budget is process-wide by design, so each test starts from zero."""
    PROCESS_BUDGET.reset()
    yield
    PROCESS_BUDGET.reset()


@pytest.fixture(scope="session")
def scenario() -> Scenario:
    return load_bundled(SCENARIO_ID)


@pytest.fixture(scope="session")
def solved(scenario: Scenario) -> Engine:
    """A complete baseline investigation. Treat as read-only."""
    engine = Engine.start(scenario, SEED)
    engine.run()
    return engine


@pytest.fixture()
def fresh(scenario: Scenario) -> Engine:
    return Engine.start(scenario, SEED)
