"""Run service: the one place that coordinates the engine with the store.

Invariant: the database only ever holds complete operations. An operation
(a batch of ticks, an intervention) runs against an in-memory engine and is
written in one transaction. If anything fails, the in-memory engine is thrown
away and the next call reloads the last consistent log from disk.
"""

from __future__ import annotations

import secrets
import threading
from typing import Any

from . import lab
from .compat import CHANGED, Compatibility, ContinuationRefused, assess, current_stamp, replay_verdict
from .engine import Engine, EngineError, IncompatibleRun, PolicyFactory, branch_prefix, verify_chain, verify_run
from .evaluation import evaluate, progress, summary_row
from .graph import ALL, project_graph
from .models import Event, Proposition
from .observer import agendas, event_rows, scenario_summary, snapshot
from .policies import make_policy
from .scenario import Scenario, bundled_scenario_ids, load_bundled
from .state import SimState, fold
from .store import Store

MAX_TICKS_PER_CALL = 100


def resolve_scenario(scenario_id: str) -> Scenario:
    """A bundled scenario, or a laboratory variant of one (`<base>.<variant>`). KeyError if neither.

    A variant is ordinary scenario data produced by validated edits to a bundled case, so a
    run of one is stored, replayed and compared like any other (and is reproducible from
    the manifest alone).
    """
    try:
        return load_bundled(scenario_id)
    except KeyError:
        base, _, variant = scenario_id.partition(".")
        manifest = lab.default_manifest()
        if variant and manifest["variants"].get(variant, {}).get("base") == base:
            try:
                return lab.build_variant(manifest, variant)
            except lab.ChallengeError as exc:
                raise KeyError(str(exc)) from exc
        raise


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


class RunService:
    def __init__(self, store: Store, policy_factory: PolicyFactory = make_policy) -> None:
        self.store = store
        self.policy_factory = policy_factory
        self._engines: dict[str, Engine] = {}
        self._compat: dict[str, Compatibility] = {}
        self._lock = threading.RLock()

    # -- lookup ---------------------------------------------------------------

    def scenarios(self) -> list[dict[str, Any]]:
        return [scenario_summary(load_bundled(name)) for name in bundled_scenario_ids()]

    def _row(self, run_id: str) -> dict[str, Any]:
        row = self.store.get_run(run_id)
        if row is None:
            raise NotFound(f"no such run: {run_id}")
        return row

    def _engine(self, run_id: str) -> Engine:
        """The live engine for a run. Raises IncompatibleRun for a log this build must not read."""
        if run_id not in self._engines:
            row = self._row(run_id)
            try:
                scenario = resolve_scenario(row["scenario_id"])
            except KeyError as exc:
                raise IncompatibleRun(f"run {run_id} uses a scenario that is not installed: {row['scenario_id']}") from exc
            events = self.store.load_events(run_id)
            broken = verify_chain(events)
            if broken is not None:
                # The store is trusted for availability, not for integrity: a log that fails
                # its own hash chain is never folded or continued.
                raise IncompatibleRun(f"run {run_id} is damaged: its hash chain is broken at event {broken}")
            engine = Engine(scenario, events, self.policy_factory)
            # Only a log this build can read at all gets here. Whether it may also be
            # continued is judged now, once per load: a stamp when it matches, else a replay.
            self._compat[run_id] = assess(scenario, events, row, self.store)
            self._engines[run_id] = engine
        return self._engines[run_id]

    def _compatibility(self, run_id: str) -> Compatibility:
        self._engine(run_id)
        return self._compat[run_id]

    def _require_continuable(self, run_id: str) -> None:
        compat = self._compatibility(run_id)
        if not compat.continuable:
            raise ContinuationRefused(f"run {run_id} is read-only: {compat.detail}")

    def _summary(self, row: dict[str, Any], state: SimState) -> dict[str, Any]:
        compat = self._compatibility(row["id"])
        return {
            "id": row["id"],
            "label": row["label"],
            "scenario_id": row["scenario_id"],
            "scenario_version": row["scenario_version"],
            "seed": row["seed"],
            "tick": state.tick,
            "max_ticks": state.max_ticks,
            "status": state.status,
            "close_reason": state.close_reason,
            "seq": state.seq,
            "head_hash": state.head_hash,
            "parent_run_id": row["parent_run_id"],
            "fork_tick": row["fork_tick"],
            "revealed": bool(row["revealed"]),
            "created_at": row["created_at"],
            "policies": {agent_id: agent.policy for agent_id, agent in state.agents.items()},
            "interventions": list(state.interventions),
            "accused": state.accusation["suspect"] if state.accusation else None,
            "compatible": True,
            "incompatible_reason": None,
            "continuable": compat.continuable,
            "compatibility": compat.public(),
        }

    @staticmethod
    def _incompatible_summary(row: dict[str, Any], reason: str) -> dict[str, Any]:
        """A run that cannot be opened: listed from stored metadata alone so it can be seen and deleted."""
        return {
            "id": row["id"],
            "label": row["label"],
            "scenario_id": row["scenario_id"],
            "scenario_version": row["scenario_version"],
            "seed": row["seed"],
            "tick": row["tick"] or 0,
            "max_ticks": 0,
            "status": "closed" if row["closed"] else "running",
            "close_reason": None,
            "seq": row["last_seq"] if row["last_seq"] is not None else -1,
            "head_hash": row["head_hash"] or "",
            "parent_run_id": row["parent_run_id"],
            "fork_tick": row["fork_tick"],
            "revealed": bool(row["revealed"]),
            "created_at": row["created_at"],
            "policies": {},
            "interventions": [],
            "accused": None,
            "compatible": False,
            "incompatible_reason": reason,
            "continuable": False,
            "compatibility": None,
        }

    def summary(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            return self._summary(self._row(run_id), self._engine(run_id).state)

    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            runs = []
            for row in self.store.list_runs():
                try:
                    runs.append(self._summary(row, self._engine(row["id"]).state))
                except IncompatibleRun as exc:
                    runs.append(self._incompatible_summary(row, str(exc)))
            return runs

    # -- mutations ------------------------------------------------------------

    def create_run(self, scenario_id: str, seed: int, policies: dict[str, str] | None = None, label: str = "") -> dict[str, Any]:
        with self._lock:
            try:
                scenario = resolve_scenario(scenario_id)
            except KeyError as exc:
                raise NotFound(str(exc)) from exc
            engine = Engine.start(scenario, seed, policies, self.policy_factory)
            run_id = secrets.token_hex(4)
            self.store.create_run(run_id, scenario.id, scenario.version, scenario.content_hash, seed, engine.events, label=label, stamp=current_stamp())
            self._engines[run_id] = engine
            self._compat[run_id] = assess(scenario, engine.events, self._row(run_id), self.store)  # covered by the stamp just written: no replay
            return self.summary(run_id)

    def _commit(self, run_id: str, operation) -> list[Event]:
        """Run an engine operation and persist exactly what it produced, or nothing."""
        with self._lock:
            engine = self._engine(run_id)
            self._require_continuable(run_id)
            before = len(engine.events)
            try:
                operation(engine)
                # One transaction: the events, and the extension of the verdict this build already holds
                # to cover what it just wrote. Either both are stored or neither is.
                self.store.append_events(
                    run_id, engine.events[before:], verified=(self._compat[run_id].public()["current_fingerprint"], len(engine.events))
                )
            except BaseException:
                self._engines.pop(run_id, None)  # memory may be ahead of disk: reload next time
                raise
            return engine.events[before:]

    def step(self, run_id: str, ticks: int = 1) -> list[dict[str, Any]]:
        if not 1 <= ticks <= MAX_TICKS_PER_CALL:
            raise BadRequest(f"ticks must be between 1 and {MAX_TICKS_PER_CALL}")
        with self._lock:
            if self._engine(run_id).state.status != "running":
                raise EngineError("the case is closed; branch from an earlier tick to continue")
            new = self._commit(run_id, lambda engine: engine.run(ticks))
            return event_rows(self._engine(run_id).scenario, new)

    def intervene(self, run_id: str, intervention_id: str) -> list[dict[str, Any]]:
        with self._lock:
            new = self._commit(run_id, lambda engine: engine.intervene(intervention_id))
            return event_rows(self._engine(run_id).scenario, new)

    def set_policy(self, run_id: str, agent_id: str, policy: str) -> list[dict[str, Any]]:
        with self._lock:
            new = self._commit(run_id, lambda engine: engine.set_policy(agent_id, policy))
            return event_rows(self._engine(run_id).scenario, new)

    def branch(self, run_id: str, tick: int, label: str = "") -> dict[str, Any]:
        with self._lock:
            row = self._row(run_id)
            engine = self._engine(run_id)
            prefix = branch_prefix(engine.events, tick)
            if self._compatibility(run_id).state == CHANGED:
                # Only the part of the log this build still reproduces can be continued from.
                verdict = replay_verdict(engine.scenario, prefix)
                if not verdict["ok"]:
                    first = self._compat[run_id].first_divergence
                    raise ContinuationRefused(
                        f"cannot branch run {run_id} at tick {tick}: the current rules do not reproduce the log up to there ({verdict['detail']}). "
                        f"Branch from a tick before event {first}"
                    )
            new_id = secrets.token_hex(4)
            self.store.create_run(
                new_id, row["scenario_id"], row["scenario_version"], row["scenario_hash"], row["seed"], prefix,
                label=label or f"branch of {row['label'] or run_id} @ tick {tick}", parent_run_id=run_id, fork_tick=tick,
                stamp={"rules_version": row.get("rules_version"), "fingerprint": row.get("fingerprint")} if row.get("fingerprint") else None,
            )
            return self.summary(new_id)

    def reveal(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._row(run_id)
            self.store.set_revealed(run_id)
            return self.summary(run_id)

    def delete(self, run_id: str) -> None:
        with self._lock:
            self._row(run_id)
            self.store.delete_run(run_id)
            self._engines.pop(run_id, None)
            self._compat.pop(run_id, None)

    # -- reads ----------------------------------------------------------------

    def _at(self, run_id: str, tick: int | None) -> tuple[Scenario, SimState, list[Event]]:
        """State and events as of the end of `tick` (default: latest)."""
        engine = self._engine(run_id)
        if tick is None or tick >= engine.state.tick:
            return engine.scenario, engine.state, engine.events
        if tick < 0:
            raise BadRequest("tick must not be negative")
        prefix = [e for e in engine.events if e.tick <= tick]
        return engine.scenario, fold(prefix), prefix

    def snapshot(self, run_id: str, tick: int | None = None) -> dict[str, Any]:
        with self._lock:
            row = self._row(run_id)
            engine = self._engine(run_id)
            scenario, state, events = self._at(run_id, tick)
            data = snapshot(scenario, state)
            data["run"] = self._summary(row, engine.state)
            data["latest_tick"] = engine.state.tick
            data["is_latest"] = state.seq == engine.state.seq
            data["progress"] = progress(scenario, state, events)
            if self._unlocked(run_id) and scenario.private.agendas:
                data["agendas"] = agendas(scenario, state)  # scenario-private: only with the solution
            return data

    def events(self, run_id: str, after: int = -1, upto_tick: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            engine = self._engine(run_id)
            selected = [e for e in engine.events if e.seq > after and (upto_tick is None or e.tick <= upto_tick)]
            return event_rows(engine.scenario, selected)

    def _unlocked(self, run_id: str) -> bool:
        """Truth may be shown once the case is closed or the user asked to see the solution."""
        return self._engine(run_id).state.status == "closed" or bool(self._row(run_id)["revealed"])

    def graph(self, run_id: str, tick: int | None = None, perspective: str = ALL) -> dict[str, Any]:
        with self._lock:
            scenario, state, _ = self._at(run_id, tick)
            try:
                data = project_graph(scenario, state, perspective)
            except KeyError as exc:
                raise NotFound(str(exc)) from exc
            data["truth_shown"] = self._unlocked(run_id)
            if data["truth_shown"]:
                for node in data["nodes"]:
                    if node["type"] == "proposition":
                        node["truth"] = scenario.truth_value(Proposition.parse(node["ref"]))
            return data

    def evaluation(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            engine = self._engine(run_id)
            base = {"progress": progress(engine.scenario, engine.state, engine.events)}
            if not self._unlocked(run_id):
                return {**base, "available": False, "reason": "The case is still open. Close it, or reveal the solution, to see the evaluation."}
            return {**base, "available": True, "result": evaluate(engine.scenario, engine.state, engine.events)}

    def verify(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._row(run_id)
            engine = self._engine(run_id)
            stored = self.store.load_events(run_id)
            report = verify_run(engine.scenario, stored, self.policy_factory)
            report["compatibility"] = self._compatibility(run_id).public()
            report["stored_matches_memory"] = [e.hash for e in stored] == [e.hash for e in engine.events]
            # Which log this report is about, so a client can tell when it has gone stale.
            report["run_id"] = run_id
            report["events"] = len(stored)
            report["tick"] = stored[-1].tick if stored else 0
            return report

    def compare(self, run_a: str, run_b: str) -> dict[str, Any]:
        with self._lock:
            sides = []
            logs = []
            for run_id in (run_a, run_b):
                row = self._row(run_id)
                engine = self._engine(run_id)
                logs.append(engine.events)
                side: dict[str, Any] = {
                    "run": self._summary(row, engine.state),
                    "progress": progress(engine.scenario, engine.state, engine.events),
                    "metrics": summary_row(engine.scenario, engine.state, engine.events) if self._unlocked(run_id) else None,
                }
                sides.append(side)
            a, b = logs
            common = 0
            for left, right in zip(a, b):
                if left.hash != right.hash:
                    break
                common += 1
            identical = common == len(a) == len(b)
            divergence = None
            if not identical:
                scenario = self._engine(run_a).scenario
                # The earlier of the two first-differing events: an intervention made after
                # tick k carries tick k, while the other run's next event already belongs to k+1.
                ticks = [log[common].tick for log in (a, b) if common < len(log)]
                divergence = {
                    "seq": common,
                    "tick": min(ticks),
                    "a": event_rows(scenario, a[common : common + 1]),
                    "b": event_rows(self._engine(run_b).scenario, b[common : common + 1]),
                }
            return {"a": sides[0], "b": sides[1], "common_events": common, "identical": identical, "divergence": divergence}
