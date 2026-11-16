"""Ground-truth isolation: an agent's view contains only what the agent legitimately learned."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import caseforge.policies
from caseforge.engine import Engine
from caseforge.models import AgentView
from caseforge.views import IsolationError, build_view, evidence_view, known_entity_ids

from .conftest import SEED, ScriptedPolicy, all_scripted, scripted_factory


def _keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _keys(item)


def test_views_never_contain_unheld_evidence_or_truth(scenario):
    """Checked for every agent at every tick of a full run, on the serialized view."""
    engine = Engine.start(scenario, SEED)
    truth = scenario.truth
    checked = 0
    while engine.state.status == "running":
        for agent_id in scenario.agent_ids:
            view = build_view(scenario, engine.state, agent_id)
            blob = view.model_dump_json()
            held = set(engine.state.agents[agent_id].holdings)
            for evidence_id, spec in scenario.evidence.items():
                if evidence_id not in held:
                    assert spec.text not in blob, f"{agent_id} can read {evidence_id} at tick {engine.state.tick}"
                    assert spec.title not in blob
            assert truth.solution not in blob
            assert not {"truth", "culprit", "solution", "key_evidence", "key_facts"} & set(_keys(view.model_dump()))
            assert {e.id for e in view.evidence} == held
            checked += 1
        engine.step()
    assert checked > 40


def test_view_exposes_only_known_entities(scenario, fresh):
    hidden = {e.id for e in scenario.private.hidden_entities}
    view = build_view(scenario, fresh.state, "okafor")
    assert not hidden & {e.id for e in view.entities}
    assert not hidden & {topic for source in view.sources for topic in source.searchable}
    # Brandt starts with his receipt, so he alone already knows of the restaurant.
    assert known_entity_ids(scenario, fresh.state, "brandt") - known_entity_ids(scenario, fresh.state, "okafor") == {"osteria"}


def test_evidence_body_lookup_refuses_unheld_records(scenario, fresh):
    with pytest.raises(IsolationError):
        evidence_view(scenario, fresh.state.agents["okafor"], "E13")
    assert evidence_view(scenario, fresh.state.agents["brandt"], "E03").text


def test_policy_receives_a_detached_view_only(scenario):
    seen: list[AgentView] = []
    policy = ScriptedPolicy(on_decide=seen.append)
    engine = Engine.start(scenario, SEED, all_scripted(scenario), scripted_factory(policy))
    engine.step()
    assert len(seen) == len(scenario.agent_ids)
    for view in seen:
        assert type(view) is AgentView
        agent = engine.state.agents[view.me.id]
        assert view.beliefs is not agent.beliefs
        # Nothing on the view object leads back to the engine, the scenario or the world state.
        for value in vars(view).values():
            assert type(value).__module__.split(".")[0] in ("builtins", "caseforge") and "Scenario" not in type(value).__name__
            assert type(value).__name__ not in ("Engine", "SimState", "AgentState", "ScenarioPrivate", "Truth")


def test_policies_import_no_module_that_can_reach_private_data():
    """Dependency rule: policies may use models, canon, reasoning and each other. Nothing else from caseforge."""
    allowed = {"canon", "models", "reasoning", "base", "baseline", "deceptive", "llm"}
    folder = Path(caseforge.policies.__file__).parent
    for path in folder.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level > 0:
                module = (node.module or "").split(".")[0]
                names = {module} if module else {alias.name for alias in node.names}
                assert names <= allowed, f"{path.name} imports {names - allowed}"
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                targets = [node.module or ""] if isinstance(node, ast.ImportFrom) else [a.name for a in node.names]
                assert not any(t.startswith("caseforge") for t in targets), f"{path.name}: use relative imports"


def test_reasoning_module_does_not_touch_scenario_or_truth():
    import caseforge.reasoning as reasoning

    tree = ast.parse(Path(reasoning.__file__).read_text(encoding="utf-8"))
    imported = {(n.module or "") for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level > 0}
    assert imported == {"models"}


def test_only_evaluation_lint_and_the_gated_service_read_the_truth_block():
    """Found by syntax, not by text search: any attribute access to `.truth` or `.truth_value`."""
    folder = Path(caseforge.policies.__file__).parent.parent
    readers = set()
    for path in folder.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(n, ast.Attribute) and n.attr in ("truth", "truth_value") for n in ast.walk(tree)):
            readers.add(path.relative_to(folder).as_posix())
    assert readers == {"scenario.py", "evaluation.py", "service.py"}, readers


def test_only_the_owner_gateway_lint_and_gated_readers_touch_agendas():
    """`private.agendas` is as private as the truth block. Found by syntax: any access to `.agendas`.

    views.py hands an agenda to its owner; scenario.py lints it; evaluation.py and
    observer.agendas() report it, and the service calls the latter only for an unlocked run.
    """
    folder = Path(caseforge.policies.__file__).parent.parent
    readers = set()
    for path in folder.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(n, ast.Attribute) and n.attr == "agendas" for n in ast.walk(tree)):
            readers.add(path.relative_to(folder).as_posix())
    assert readers == {"scenario.py", "views.py", "observer.py", "evaluation.py", "service.py"}, readers
    # Policies get the agenda through the view only.
    for path in (folder / "policies").glob("*.py"):
        assert "private" not in {n.attr for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(n, ast.Attribute)}


def test_only_the_owner_gateway_and_the_lint_touch_observations():
    """What an agent saw is private scenario data. Found by syntax: any access to `private.observations`.

    views.py hands it to its owner (`observations_of`); scenario.py lints it. Every other module
    goes through the gateway and has to say on whose behalf it is asking.
    """
    folder = Path(caseforge.policies.__file__).parent.parent
    readers = set()
    for path in folder.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "observations" and isinstance(node.value, ast.Attribute) and node.value.attr == "private":
                readers.add(path.relative_to(folder).as_posix())
    assert readers == {"scenario.py", "views.py"}, readers
