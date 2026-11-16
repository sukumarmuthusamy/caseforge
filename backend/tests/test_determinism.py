"""Same scenario, seed and inputs must give a byte-identical event log."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from caseforge.canon import DeterministicRng, canonical_json
from caseforge.engine import Engine

from .conftest import SEED


def test_same_seed_gives_identical_log(scenario, solved):
    again = Engine.start(scenario, SEED)
    again.run()
    assert [e.hash for e in again.events] == [e.hash for e in solved.events]
    assert again.state.head_hash == solved.state.head_hash


def test_different_seeds_diverge(scenario):
    hashes = set()
    for seed in (1, 2, 3):
        engine = Engine.start(scenario, seed)
        engine.run(5)
        hashes.add(engine.state.head_hash)
    assert len(hashes) == 3


def test_log_is_independent_of_hash_randomization(solved):
    """Set and dict ordering must never reach the log: run in fresh interpreters with different hash seeds."""
    code = (
        "from caseforge.scenario import load_bundled;"
        "from caseforge.engine import Engine;"
        f"e = Engine.start(load_bundled('missing_prototype'), {SEED}); e.run(); print(e.state.head_hash)"
    )
    heads = set()
    for hash_seed in ("0", "1", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True)
        heads.add(out.stdout.strip())
    assert heads == {solved.state.head_hash}


def _walk(value):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def test_events_hold_no_floats_and_no_wall_clock(solved):
    for event in solved.events:
        assert not any(isinstance(v, float) for v in _walk(event.data)), event
        assert set(event.body()) == {"seq", "tick", "type", "actor", "cause", "data"}
    keys = {k for event in solved.events for v in _walk(event.data) if isinstance(v, dict) for k in v}
    assert not {k for k in keys if "time" in k.lower() or "date" in k.lower() or "uuid" in k.lower()}


def test_sequence_and_ticks_are_monotonic(solved):
    assert [e.seq for e in solved.events] == list(range(len(solved.events)))
    ticks = [e.tick for e in solved.events]
    assert ticks == sorted(ticks)


def test_canonical_json_rejects_floats_and_orders_keys():
    assert canonical_json({"b": 1, "a": [2, {"d": 3, "c": 4}]}) == '{"a":[2,{"c":4,"d":3}],"b":1}'
    with pytest.raises(TypeError):
        canonical_json({"a": 0.5})
    with pytest.raises(TypeError):
        canonical_json({1: "a"})


def test_rng_is_a_pure_function_of_its_context():
    # Golden values: these must not change across Python versions or platforms.
    rng = DeterministicRng(7, 3, "okafor", "decide")
    assert rng.pick(["a", "b", "c", "d", "e"]) == "e"
    assert rng.pick(list(range(100))) == 96
    assert rng.shuffled(["okafor", "brandt", "reyes", "nair"]) == ["reyes", "okafor", "brandt", "nair"]
    names = ["okafor", "brandt", "reyes", "nair"]
    assert DeterministicRng(0, 1, "order").shuffled(names) == DeterministicRng(0, 1, "order").shuffled(list(reversed(names)))
    orders = {tuple(DeterministicRng(0, tick, "order").shuffled(names)) for tick in range(1, 21)}
    assert len(orders) > 1, "turn order should vary between ticks"
