"""The simulation engine: tick loop, interventions, branching and verification.

The engine is the only writer of events. Every state change, live or replayed,
goes through `apply_event`.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from .actions import ActionError, Dirty, apply_action, validate_action
from .canon import GENESIS_HASH, DeterministicRng, canonical_json, chain_hash
from .models import (
    ENGINE_VERSION,
    Decision,
    DecisionTrace,
    Event,
    Proposition,
    Wait,
    normalize_event_data,
)
from .policies import Policy, make_policy
from .reasoning import revise
from .scenario import ANONYMOUS, Scenario
from .state import SimState, apply_event, fold
from .views import build_view, context_for_agent, items_for_agent, observation_id, observations_of

STANCE = {"believed": "accepted", "rejected": "rejected"}  # anything else is "questioned"

PolicyFactory = Callable[[str], Policy]


class EngineError(Exception):
    """A driver-level request that cannot be honoured (closed case, unknown intervention, ...)."""


class IncompatibleRun(EngineError):
    """A stored log that this build must not interpret or continue."""


def check_compatible(scenario: Scenario, events: list[Event]) -> None:
    """Refuse a log recorded by another engine version or against another scenario.

    Checked before folding: a reducer from a different version may misread the
    log rather than fail, and a mixed-version history could never be verified.
    There is no migration path; an incompatible run can be listed and deleted.
    """
    if not events:
        return
    first = events[0]
    if first.type != "RunStarted":
        raise IncompatibleRun("event log does not begin with RunStarted")
    recorded = first.data.get("engine_version")
    if recorded != ENGINE_VERSION:
        raise IncompatibleRun(f"run was recorded by engine version {recorded!r}; this build is engine version {ENGINE_VERSION!r} and will not reinterpret it")
    if first.data.get("scenario_hash") != scenario.content_hash:
        raise IncompatibleRun("run was recorded against a different version of the scenario")


class Engine:
    def __init__(self, scenario: Scenario, events: Iterable[Event] = (), policy_factory: PolicyFactory = make_policy) -> None:
        self.scenario = scenario
        self.events: list[Event] = list(events)
        check_compatible(scenario, self.events)
        self.state: SimState = fold(self.events)
        self._policy_factory = policy_factory
        self._policies: dict[str, Policy] = {}
        self._tick = self.state.tick

    # -- construction ---------------------------------------------------------

    @classmethod
    def start(
        cls,
        scenario: Scenario,
        seed: int,
        policies: dict[str, str] | None = None,
        policy_factory: PolicyFactory = make_policy,
    ) -> "Engine":
        engine = cls(scenario, (), policy_factory)
        assigned = {agent: "baseline" for agent in scenario.agent_ids}
        for agent, name in (policies or {}).items():
            if agent not in assigned:
                raise EngineError(f"unknown agent in policy assignment: {agent}")
            assigned[agent] = name
        for name in sorted(set(assigned.values())):
            engine._policy(name)  # fail before the run exists if a policy cannot be built
        engine._emit("RunStarted", "engine", {
            "scenario_id": scenario.id,
            "scenario_version": scenario.version,
            "scenario_hash": scenario.content_hash,
            "engine_version": ENGINE_VERSION,
            "seed": seed,
            "agents": list(scenario.agent_ids),
            "policies": assigned,
            "max_ticks": scenario.case.max_ticks,
        })
        dirty: Dirty = {}
        for agent in scenario.agent_ids:
            for evidence_id in scenario.private.initial_holdings.get(agent, ()):
                spec = scenario.evidence[evidence_id]
                engine._emit("EvidenceObserved", agent, {"agent": agent, "evidence": evidence_id, "source": spec.source, "via": "initial"})
                dirty.setdefault(agent, []).append(evidence_id)
            for index, _ in enumerate(observations_of(scenario, agent)):
                dirty.setdefault(agent, []).append(observation_id(index))
        engine._revise(dirty, cause=0)
        return engine

    # -- event plumbing -------------------------------------------------------

    def _emit(self, event_type: str, actor: str, data: dict[str, Any], cause: int | None = None) -> Event:
        seq = len(self.events)
        prev = self.events[-1].hash if self.events else GENESIS_HASH
        body = {
            "seq": seq,
            "tick": self._tick,
            "type": event_type,
            "actor": actor,
            "cause": cause,
            "data": normalize_event_data(event_type, data),
        }
        event = Event(**body, hash=chain_hash(prev, body))
        self.events.append(event)
        apply_event(self.state, event)
        return event

    def _policy(self, name: str) -> Policy:
        if name not in self._policies:
            try:
                self._policies[name] = self._policy_factory(name)
            except EngineError:
                raise
            except Exception as exc:
                raise EngineError(f"policy {name!r} is not available: {exc}") from exc
        return self._policies[name]

    # -- belief revision ------------------------------------------------------

    def _revise(self, dirty: Dirty, cause: int | None) -> None:
        """Recompute beliefs for agents who just learned something and record the difference."""
        for agent_id in sorted(dirty):
            agent = self.state.agents[agent_id]
            revision = revise(items_for_agent(self.scenario, self.state, agent_id), context_for_agent(self.scenario, agent_id))
            changes: dict[str, Any] = {}
            for key, entry in revision.beliefs.items():
                if agent.beliefs.get(key) != entry:
                    changes[key] = entry.model_dump(mode="json")
            for key in agent.beliefs:
                if key not in revision.beliefs:
                    changes[key] = None
            suspects_changed = agent.suspects != revision.suspects
            if changes or suspects_changed or agent.prime_suspect != revision.prime_suspect:
                self._emit("BeliefsRevised", agent_id, {
                    "agent": agent_id,
                    "because": list(dirty[agent_id]),
                    "changes": dict(sorted(changes.items())),
                    "suspects": {name: a.model_dump(mode="json") for name, a in revision.suspects.items()},
                    "prime_before": agent.prime_suspect,
                    "prime_after": revision.prime_suspect,
                }, cause)
            for key in revision.contradictions:
                if key not in agent.contradictions:
                    a, b = key.split("|")
                    self._emit("ContradictionRecognized", agent_id, {"agent": agent_id, "a": a, "b": b}, cause)
            # What the agent can now check of each speaker's word. Recorded, like a belief,
            # as the outcome of the revision; the reducer only stores it.
            current = {speaker: entry.current for speaker, entry in agent.credibility.items() if entry.current is not None}
            for speaker in sorted(set(current) | set(revision.credibility)):
                after = revision.credibility.get(speaker)
                if current.get(speaker) != after:
                    self._emit("CredibilityRevised", agent_id, {
                        "agent": agent_id,
                        "speaker": speaker,
                        "credibility": after.model_dump(mode="json") if after else None,
                        "before": current[speaker].standing if speaker in current else None,
                        "because": list(dirty[agent_id]),
                    }, cause)
            # What the agent makes of each thing it was told: on first hearing, and on every change.
            for statement in sorted(self.state.statements.values(), key=lambda s: s.seq):
                if statement.recipient != agent_id:
                    continue
                belief = revision.beliefs.get(statement.proposition)
                status = belief.status if belief else "unknown"
                stance = STANCE.get(status, "questioned")
                if not statement.stances or statement.stances[-1].stance != stance:
                    self._emit("StatementWeighed", agent_id, {
                        "agent": agent_id, "statement": statement.id, "stance": stance, "belief": status,
                    }, cause)
        self._notice(cause)

    def _notice(self, cause: int | None) -> None:
        """Record every answer that an agent can now see left a record out.

        A requester notices once it holds, by whatever route, a record that the
        logged search behind an earlier answer had found and not delivered. The
        check is exact (it compares against the search result in the log), so an
        honest "nothing yet" for a record that only became retrievable later is
        never mistaken for withholding.
        """
        for agent_id in sorted(self.state.agents):
            agent = self.state.agents[agent_id]
            seen = {(d.request, d.evidence) for d in agent.discrepancies}
            for request in sorted(self.state.requests.values(), key=lambda r: r.seq):
                if request.sender != agent_id:
                    continue
                for evidence_id in request.withheld:
                    if evidence_id in agent.holdings and (request.id, evidence_id) not in seen:
                        self._emit("DiscrepancyNoticed", agent_id, {
                            "agent": agent_id, "against": request.recipient, "request": request.id, "evidence": evidence_id,
                        }, cause)

    # -- ticking --------------------------------------------------------------

    def step(self) -> list[Event]:
        """Advance one tick: every agent acts once, in a seeded order."""
        if self.state.status != "running":
            raise EngineError("the case is closed; branch from an earlier tick to continue")
        start = len(self.events)
        self._tick = self.state.tick + 1
        order = DeterministicRng(self.state.seed, self._tick, "order").shuffled(self.scenario.agent_ids)
        self._emit("TickStarted", "engine", {"order": order})
        for agent_id in order:
            if self.state.status != "running":
                break
            self._act(agent_id)
        if self.state.status == "running" and self._tick >= self.state.max_ticks:
            self._emit("CaseClosed", "engine", {"reason": "tick_limit"})
        return self.events[start:]

    def run(self, ticks: int | None = None) -> list[Event]:
        start = len(self.events)
        remaining = ticks
        while self.state.status == "running" and (remaining is None or remaining > 0):
            self.step()
            if remaining is not None:
                remaining -= 1
        return self.events[start:]

    def _act(self, agent_id: str) -> None:
        view = build_view(self.scenario, self.state, agent_id)
        policy_name = self.state.agents[agent_id].policy
        rng = DeterministicRng(self.state.seed, self._tick, agent_id, "decide")
        try:
            decision = self._policy(policy_name).decide(view, rng)
            if not isinstance(decision, Decision):
                raise TypeError("policy did not return a Decision")
            canonical_json(decision.model_dump(mode="json"))  # must be loggable: no floats, string keys
        except Exception as exc:  # a broken policy must not break the run
            decision = Decision(
                action=Wait(),
                trace=DecisionTrace(policy=policy_name, reason=f"policy raised {type(exc).__name__}: {exc}"[:300]),
            )
        action = decision.action
        payload = {
            "agent": agent_id,
            "action": action.model_dump(mode="json"),
            "trace": decision.trace.model_dump(mode="json"),
        }
        try:
            validate_action(self.scenario, self.state, agent_id, action)
        except ActionError as error:
            self._emit("ActionRejected", agent_id, {**payload, "code": error.code, "message": error.message})
            return
        taken = self._emit("ActionTaken", agent_id, payload)
        dirty = apply_action(
            self.scenario, self.state, agent_id, action,
            lambda event_type, actor, data: self._emit(event_type, actor, data, taken.seq),
        )
        self._revise(dirty, taken.seq)

    # -- user operations ------------------------------------------------------

    def intervene(self, intervention_id: str) -> list[Event]:
        spec = self.scenario.interventions.get(intervention_id)
        if spec is None:
            raise EngineError(f"unknown intervention: {intervention_id}")
        if self.state.status != "running":
            raise EngineError("the case is closed; branch from an earlier tick to intervene")
        if intervention_id in self.state.interventions:
            raise EngineError(f"intervention {intervention_id} was already applied in this run")
        start = len(self.events)
        self._tick = self.state.tick
        applied = self._emit("InterventionApplied", "user", {"intervention": intervention_id, "kind": spec.kind})
        dirty: Dirty = {}
        if spec.kind == "release_evidence":
            for recipient in spec.recipients:
                if spec.evidence not in self.state.agents[recipient].holdings:
                    self._emit("EvidenceReleased", "user", {"evidence": spec.evidence, "recipient": recipient, "intervention": intervention_id}, applied.seq)
                    dirty.setdefault(recipient, []).append(spec.evidence)
        elif spec.kind == "spread_rumor":
            claim_id = f"C{self.state.seq + 1}"
            self._emit("ClaimPublished", "user", {
                "claim": claim_id, "by": ANONYMOUS, "proposition": spec.proposition.key,
                "cited": [], "audience": list(spec.recipients), "text": spec.text,
            }, applied.seq)
            for recipient in spec.recipients:
                dirty.setdefault(recipient, []).append(claim_id)
        elif spec.kind == "grant_access":
            self._emit("AccessGranted", "user", {"agent": spec.agent, "source": spec.source, "intervention": intervention_id}, applied.seq)
        self._revise(dirty, applied.seq)
        return self.events[start:]

    def set_policy(self, agent_id: str, policy_name: str) -> list[Event]:
        if agent_id not in self.state.agents:
            raise EngineError(f"unknown agent: {agent_id}")
        if self.state.status != "running":
            raise EngineError("the case is closed")
        self._policy(policy_name)
        start = len(self.events)
        self._tick = self.state.tick
        if self.state.agents[agent_id].policy != policy_name:
            self._emit("PolicyChanged", "user", {"agent": agent_id, "policy": policy_name})
        return self.events[start:]


# ---------------------------------------------------------------------------
# Branching
# ---------------------------------------------------------------------------


def branch_prefix(events: list[Event], tick: int) -> list[Event]:
    """Events of a run up to and including `tick` (and any interventions made before the next tick)."""
    if not events:
        raise EngineError("cannot branch an empty run")
    if tick < 0 or tick > events[-1].tick:
        raise EngineError(f"tick {tick} is outside this run (0..{events[-1].tick})")
    prefix = [e for e in events if e.tick <= tick]
    if any(e.type == "CaseClosed" for e in prefix):
        raise EngineError("the case is already closed at that tick; branch from an earlier one")
    return prefix


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_chain(events: list[Event]) -> int | None:
    """Return the seq of the first event whose hash or position is wrong, or None."""
    prev = GENESIS_HASH
    for index, event in enumerate(events):
        if event.seq != index or event.hash != chain_hash(prev, event.body()):
            return index
        prev = event.hash
    return None


class _RecordedPolicy:
    """Feeds back the decisions stored in an event log. Used to replay a run without its policies."""

    deterministic = True

    def __init__(self, name: str, decisions: dict[tuple[int, str], Decision]) -> None:
        self.name = name
        self._decisions = decisions

    def decide(self, view, rng) -> Decision:
        return self._decisions[(view.tick, view.me.id)]


def _recorded_decisions(events: list[Event]) -> dict[tuple[int, str], Decision]:
    decisions: dict[tuple[int, str], Decision] = {}
    for event in events:
        if event.type in ("ActionTaken", "ActionRejected"):
            decisions[(event.tick, event.data["agent"])] = Decision.model_validate(
                {"action": event.data["action"], "trace": event.data["trace"]}
            )
    return decisions


def resimulate(scenario: Scenario, events: list[Event], mode: str, policy_factory: PolicyFactory = make_policy) -> dict[str, Any]:
    """Re-run a recorded log and compare it event by event.

    mode "decisions": recorded decisions are fed back through validation,
    effects and belief revision. Proves the engine is a deterministic function
    of (scenario, seed, decisions, interventions). Works for any policy.

    mode "policies": the policies themselves are run again. Proves the whole
    run is reproducible. Skipped when a non-deterministic policy took part.
    """
    if not events or events[0].type != "RunStarted":
        return {"ok": False, "mode": mode, "detail": "log does not begin with RunStarted", "first_divergence": 0}
    started = events[0].data
    names = set(started["policies"].values()) | {e.data["policy"] for e in events if e.type == "PolicyChanged"}

    if mode == "decisions":
        decisions = _recorded_decisions(events)
        factory: PolicyFactory = lambda name: _RecordedPolicy(name, decisions)
    else:
        try:
            nondeterministic = sorted(n for n in names if not policy_factory(n).deterministic)
        except Exception as exc:
            return {"ok": None, "mode": mode, "detail": f"skipped: a policy could not be built ({exc})", "first_divergence": None}
        if nondeterministic:
            return {"ok": None, "mode": mode, "detail": f"skipped: non-deterministic policy in use ({', '.join(nondeterministic)})", "first_divergence": None}
        factory = policy_factory

    try:
        replica = Engine.start(scenario, started["seed"], dict(started["policies"]), factory)
        for event in events:
            if event.type == "TickStarted":
                replica.step()
            elif event.type == "InterventionApplied":
                replica.intervene(event.data["intervention"])
            elif event.type == "PolicyChanged":
                replica.set_policy(event.data["agent"], event.data["policy"])
    except Exception as exc:
        return {"ok": False, "mode": mode, "detail": f"re-run failed: {type(exc).__name__}: {exc}", "first_divergence": None}

    for original, again in zip(events, replica.events):
        if original.hash != again.hash:
            return {"ok": False, "mode": mode, "detail": f"diverged at event {original.seq} ({original.type})", "first_divergence": original.seq}
    if len(events) != len(replica.events):
        shorter = min(len(events), len(replica.events))
        return {"ok": False, "mode": mode, "detail": f"length differs: recorded {len(events)}, re-run {len(replica.events)}", "first_divergence": shorter}
    return {"ok": True, "mode": mode, "detail": f"{len(events)} events reproduced exactly", "first_divergence": None}


def verify_run(scenario: Scenario, events: list[Event], policy_factory: PolicyFactory = make_policy) -> dict[str, Any]:
    """All three checks: hash chain, fold, decision replay, full re-simulation."""
    bad = verify_chain(events)
    chain = {"ok": bad is None, "detail": "hash chain intact" if bad is None else f"hash chain broken at event {bad}", "first_divergence": bad}
    try:
        folded = fold(events)
        fold_check = {"ok": True, "detail": f"state rebuilt from {len(events)} events (tick {folded.tick}, {folded.status})"}
    except Exception as exc:
        fold_check = {"ok": False, "detail": f"fold failed: {exc}"}
    return {
        "chain": chain,
        "fold": fold_check,
        "decisions": resimulate(scenario, events, "decisions", policy_factory),
        "policies": resimulate(scenario, events, "policies", policy_factory),
        "head_hash": events[-1].hash if events else GENESIS_HASH,
    }
