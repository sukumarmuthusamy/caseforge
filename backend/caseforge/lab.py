"""Counterfactual laboratory: controlled variations of the bundled cases, run against frozen rules.

What this is
------------
A manifest (`challenges/counterfactual.json`) lists *variants* of a bundled
scenario and *challenges* that run a variant under a stated policy assignment.
Each challenge says beforehand who did it, what a careful investigation
should do, and what its author expects the current rules to do. The runner
plays the challenge over a range of seeds and reports what happened, in the
evaluation's own categories, without changing a rule.

Two kinds of challenge, never mixed in one table:

- **playable**: a variant is the base scenario's file with a list of edits
  applied. It must pass the ordinary models and the ordinary lint, and it is
  played by the ordinary engine with the ordinary policies. Nothing here
  bypasses a permission or an action check.
- **reasoning**: a list of items handed to `reasoning.revise`. No scenario, no
  agents, no acquisition. It says what the rules conclude from given
  information and makes no claim that the situation can be played.

What an expectation is
----------------------
- `contract`: must hold whatever the rules are. A failure is a software defect.
- `design`: the condition the challenge exists to create (the lie was told;
  the stated culprit is the scenario's). A failure means that run does not
  test what it claims to, and it is counted apart.
- `ideal`: what a careful investigator would do. A failure is a limit of the
  policy or the reasoner, not a bug, and is reported as such.

Every expectation carries its author's prediction (`holds`, `fails` or
`mixed`), written before the first run, so the report can show where the
author was wrong about his own rules.

What this is not
----------------
The challenges were written by the author of the rules, with the rules in
view. They are internally pre-registered, not an independent benchmark. The
manifest records the rule set, engine version, scenario hashes and a
fingerprint of the reasoner and policy sources it was registered against;
the runner refuses to report under any other without being told to.

This module edits scenario *data* the way an author edits a file, and reads
outcomes from `evaluation.evaluate`. It hands no truth to any policy.
"""

from __future__ import annotations

import copy
import functools
import hashlib
import json
import statistics
from collections import Counter
from importlib import resources
from typing import Any, Callable, Iterable

from .engine import Engine, verify_run
from .evaluation import evaluate
from .models import ENGINE_VERSION, EvidenceSpec, Proposition, ScenarioPrivate, ScenarioPublic, SourceSpec
from .reasoning import RULES_VERSION, Item, ReasoningContext, meets_standard, revise
from .scenario import Scenario, lint, load_bundled, reach_report

LABEL = "Internally pre-registered challenges, written by the author of the rules. Not an independent benchmark."
CATEGORIES = ("correct_supported", "correct_unsupported", "wrong_supported", "wrong_unsupported", "unresolved")
VERDICTS = ("meets_ideal", "falls_short", "invalid_instance", "contract_violation")
KINDS = ("contract", "design", "ideal")
PREDICTIONS = ("holds", "fails", "mixed")
REPLAY_LEVELS = ("chain", "fold", "decisions", "policies")
BEHAVIOUR_SOURCES = ("reasoning.py", "policies/__init__.py", "policies/base.py", "policies/baseline.py", "policies/deceptive.py")


def _supported() -> str:
    return " or ".join(str(v) for v in SUPPORTED_MANIFEST_VERSIONS)


class ChallengeError(ValueError):
    """A manifest, a transformation or a challenge is not valid. The message says which and why."""


# --------------------------------------------------------------------------
# Manifest and the frozen baseline
# --------------------------------------------------------------------------


def load_manifest(path: str | None = None) -> dict:
    if path is None:
        text = resources.files("caseforge").joinpath("challenges", "counterfactual.json").read_text(encoding="utf-8")
    else:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    manifest = json.loads(text)
    check_manifest(manifest)
    return manifest


@functools.cache
def default_manifest() -> dict:
    """The manifest this build ships, loaded and checked once. Callers must not edit it."""
    return load_manifest()


def behaviour_fingerprint() -> str:
    """A hash of the reasoner and the deterministic policies, independent of line endings."""
    digest = hashlib.sha256()
    for name in BEHAVIOUR_SOURCES:
        text = resources.files("caseforge").joinpath(*name.split("/")).read_text(encoding="utf-8").replace("\r\n", "\n")
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update(text.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def current_baseline(scenario_ids: Iterable[str]) -> dict:
    return {
        "engine_version": ENGINE_VERSION,
        "rules_version": RULES_VERSION,
        "behaviour_fingerprint": behaviour_fingerprint(),
        "scenarios": {
            scenario_id: {"version": load_bundled(scenario_id).version, "hash": load_bundled(scenario_id).content_hash[:12]}
            for scenario_id in sorted(scenario_ids)
        },
    }


def baseline_drift(manifest: dict) -> list[str]:
    """Differences between what the manifest was registered against and the running build."""
    frozen = manifest["frozen"]
    now = current_baseline(frozen["scenarios"])
    drift = []
    for key in ("engine_version", "rules_version", "behaviour_fingerprint"):
        if frozen[key] != now[key]:
            drift.append(f"{key}: registered against {frozen[key]!r}, running {now[key]!r}")
    for scenario_id, registered in sorted(frozen["scenarios"].items()):
        if registered != now["scenarios"][scenario_id]:
            drift.append(f"scenario {scenario_id}: registered against {registered}, running {now['scenarios'][scenario_id]}")
    return drift


SUPPORTED_MANIFEST_VERSIONS = (1,)


def check_manifest(manifest: dict) -> None:
    """Structure only. Whether a variant is a valid scenario is decided when it is built.

    The schema version is checked first and on its own, before anything else in the
    file is read: a manifest of another schema must not be interpreted with this
    one's semantics, and must never come out as registered and compatible.
    """
    if not isinstance(manifest, dict):
        raise ChallengeError(f"manifest: expected a JSON object, got {type(manifest).__name__}")
    if "manifest_version" not in manifest:
        raise ChallengeError(f"manifest: missing 'manifest_version'. This build reads version {_supported()}")
    version = manifest["manifest_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise ChallengeError(f"manifest: 'manifest_version' must be an integer, got {version!r}. This build reads version {_supported()}")
    if version not in SUPPORTED_MANIFEST_VERSIONS:
        raise ChallengeError(
            f"manifest: version {version} is not supported. This build reads version {_supported()}; "
            "a manifest of another schema has to be converted or run with the build that wrote it"
        )
    for key in ("label", "frozen", "variants", "challenges"):
        if key not in manifest:
            raise ChallengeError(f"manifest: missing {key!r}")
    variants = manifest["variants"]
    seen: set[str] = set()
    for challenge in manifest["challenges"]:
        where = f"challenge {challenge.get('id', '?')!r}"
        for key in ("id", "kind", "category", "question", "culprit", "expectations"):
            if key not in challenge:
                raise ChallengeError(f"{where}: missing {key!r}")
        if challenge["id"] in seen:
            raise ChallengeError(f"{where}: defined twice")
        seen.add(challenge["id"])
        if challenge["kind"] == "playable":
            if challenge.get("variant") not in variants:
                raise ChallengeError(f"{where}: unknown variant {challenge.get('variant')!r}")
            checks = PLAY_CHECKS
        elif challenge["kind"] == "reasoning":
            for key in ("world", "items"):
                if key not in challenge:
                    raise ChallengeError(f"{where}: a reasoning fixture needs {key!r}")
            checks = REASONING_CHECKS
        else:
            raise ChallengeError(f"{where}: kind must be 'playable' or 'reasoning', not {challenge['kind']!r}")
        names = set()
        if not challenge["expectations"]:
            raise ChallengeError(f"{where}: states no expectation")
        for expectation in challenge["expectations"]:
            label = f"{where}, expectation {expectation.get('id', '?')!r}"
            for key in ("id", "kind", "check", "predicted", "says"):
                if key not in expectation:
                    raise ChallengeError(f"{label}: missing {key!r}")
            if expectation["id"] in names:
                raise ChallengeError(f"{label}: defined twice")
            names.add(expectation["id"])
            if expectation["kind"] not in KINDS:
                raise ChallengeError(f"{label}: kind must be one of {KINDS}")
            if expectation["predicted"] not in PREDICTIONS:
                raise ChallengeError(f"{label}: predicted must be one of {PREDICTIONS}")
            if expectation["check"] not in checks:
                raise ChallengeError(f"{label}: unknown check {expectation['check']!r} for a {challenge['kind']} challenge")
    for variant_id, variant in variants.items():
        for key in ("base", "revision", "summary", "ops"):
            if key not in variant:
                raise ChallengeError(f"variant {variant_id!r}: missing {key!r}")


def find_challenge(manifest: dict, challenge_id: str) -> dict:
    for challenge in manifest["challenges"]:
        if challenge["id"] == challenge_id:
            return challenge
    known = ", ".join(c["id"] for c in manifest["challenges"])
    raise ChallengeError(f"unknown challenge {challenge_id!r}. Known: {known}")


def select(manifest: dict, names: Iterable[str]) -> list[dict]:
    """Challenges by id, or by collection: all, playable, reasoning, or a category."""
    chosen: list[dict] = []
    for name in names or ["all"]:
        if name == "all":
            matches = list(manifest["challenges"])
        elif name in ("playable", "reasoning"):
            matches = [c for c in manifest["challenges"] if c["kind"] == name]
        elif any(c["category"] == name for c in manifest["challenges"]):
            matches = [c for c in manifest["challenges"] if c["category"] == name]
        else:
            matches = [find_challenge(manifest, name)]
        chosen.extend(c for c in matches if c not in chosen)
    return chosen


# --------------------------------------------------------------------------
# Transformations: edits to a scenario file, each one checked
# --------------------------------------------------------------------------


def _by_id(items: list[dict], item_id: str, what: str) -> dict:
    for item in items:
        if item["id"] == item_id:
            return item
    raise ChallengeError(f"no {what} {item_id!r}")


def _set_fields(target: dict, fields: dict, allowed: Iterable[str], what: str) -> None:
    if not fields:
        raise ChallengeError(f"{what}: no fields given")
    allowed = set(allowed)
    for key, value in fields.items():
        if key == "id":
            raise ChallengeError(f"{what}: an id cannot be changed")
        if key not in allowed:
            raise ChallengeError(f"{what}: unknown field {key!r}")
    if all(target.get(key) == value for key, value in fields.items()):
        raise ChallengeError(f"{what}: changes nothing")
    target.update(copy.deepcopy(fields))


def _op_evidence_add(data: dict, op: dict) -> None:
    record = op["record"]
    if any(e["id"] == record["id"] for e in data["private"]["evidence"]):
        raise ChallengeError(f"evidence {record['id']!r} already exists")
    data["private"]["evidence"].append(copy.deepcopy(record))


def _op_evidence_set(data: dict, op: dict) -> None:
    target = _by_id(data["private"]["evidence"], op["id"], "evidence")
    _set_fields(target, op["fields"], EvidenceSpec.model_fields, f"evidence {op['id']}")


def _op_evidence_remove(data: dict, op: dict) -> None:
    data["private"]["evidence"].remove(_by_id(data["private"]["evidence"], op["id"], "evidence"))


def _op_source_set(data: dict, op: dict) -> None:
    target = _by_id(data["public"]["sources"], op["id"], "source")
    _set_fields(target, op["fields"], SourceSpec.model_fields, f"source {op['id']}")


def _op_entity_add(data: dict, op: dict) -> None:
    entity = op["entity"]
    everything = data["public"]["entities"] + data["private"].setdefault("hidden_entities", [])
    if any(e["id"] == entity["id"] for e in everything):
        raise ChallengeError(f"entity {entity['id']!r} already exists")
    (data["private"]["hidden_entities"] if op.get("hidden") else data["public"]["entities"]).append(copy.deepcopy(entity))


def _op_observation_add(data: dict, op: dict) -> None:
    seen = data["private"].setdefault("observations", {}).setdefault(op["agent"], [])
    if op["proposition"] in seen:
        raise ChallengeError(f"{op['agent']} already has the observation {op['proposition']}")
    seen.append(op["proposition"])


def _op_observation_remove(data: dict, op: dict) -> None:
    seen = data["private"].get("observations", {}).get(op["agent"], [])
    if op["proposition"] not in seen:
        raise ChallengeError(f"{op['agent']} has no observation {op['proposition']}")
    seen.remove(op["proposition"])
    if not seen:
        del data["private"]["observations"][op["agent"]]


def _op_agenda_set(data: dict, op: dict) -> None:
    agendas = data["private"].setdefault("agendas", {})
    if op["agenda"] is None:
        if op["agent"] not in agendas:
            raise ChallengeError(f"{op['agent']} has no agenda to remove")
        del agendas[op["agent"]]
    else:
        if agendas.get(op["agent"]) == op["agenda"]:
            raise ChallengeError(f"agenda of {op['agent']}: changes nothing")
        agendas[op["agent"]] = copy.deepcopy(op["agenda"])


def _op_truth_set(data: dict, op: dict) -> None:
    _set_fields(data["private"]["truth"], op["fields"], ("culprit", "solution", "key_evidence", "key_facts"), "truth")


def _op_truth_facts(data: dict, op: dict) -> None:
    facts = data["private"]["truth"]["facts"]
    add, remove = op.get("add", []), op.get("remove", [])
    if not add and not remove:
        raise ChallengeError("truth.facts: nothing to add or remove")
    for fact in remove:
        if fact not in facts:
            raise ChallengeError(f"truth.facts: {fact} is not a fact, so it cannot be removed")
        facts.remove(fact)
    for fact in add:
        if fact in facts:
            raise ChallengeError(f"truth.facts: {fact} is already a fact")
        facts.append(fact)


def _op_holdings_set(data: dict, op: dict) -> None:
    holdings = data["private"].setdefault("initial_holdings", {})
    if holdings.get(op["agent"], []) == op["evidence"]:
        raise ChallengeError(f"holdings of {op['agent']}: changes nothing")
    holdings[op["agent"]] = list(op["evidence"])


def _op_intervention_remove(data: dict, op: dict) -> None:
    data["public"]["interventions"].remove(_by_id(data["public"]["interventions"], op["id"], "intervention"))


OPS: dict[str, tuple[Callable[[dict, dict], None], tuple[str, ...]]] = {
    "evidence.add": (_op_evidence_add, ("record",)),
    "evidence.set": (_op_evidence_set, ("id", "fields")),
    "evidence.remove": (_op_evidence_remove, ("id",)),
    "source.set": (_op_source_set, ("id", "fields")),
    "entity.add": (_op_entity_add, ("entity",)),
    "observation.add": (_op_observation_add, ("agent", "proposition")),
    "observation.remove": (_op_observation_remove, ("agent", "proposition")),
    "agenda.set": (_op_agenda_set, ("agent", "agenda")),
    "truth.set": (_op_truth_set, ("fields",)),
    "truth.facts": (_op_truth_facts, ()),
    "holdings.set": (_op_holdings_set, ("agent", "evidence")),
    "intervention.remove": (_op_intervention_remove, ("id",)),
}


def apply_ops(data: dict, ops: list[dict]) -> dict:
    """A deep copy of `data` with every edit applied, or a ChallengeError naming the edit that failed.

    An edit that names something absent, uses an unknown field, or changes
    nothing is an error: a transformation that silently does less than it
    says would make a challenge mean something other than its description.
    """
    out = copy.deepcopy(data)
    for index, op in enumerate(ops):
        name = op.get("op")
        where = f"edit {index + 1} ({name})"
        if name not in OPS:
            raise ChallengeError(f"{where}: unknown edit. Known: {', '.join(sorted(OPS))}")
        if not op.get("why"):
            raise ChallengeError(f"{where}: every edit says why it is made")
        handler, required = OPS[name]
        for key in required:
            if key not in op:
                raise ChallengeError(f"{where}: missing {key!r}")
        unknown = set(op) - set(required) - {"op", "why", "hidden", "add", "remove"}
        if unknown:
            raise ChallengeError(f"{where}: unknown keys {sorted(unknown)}")
        try:
            handler(out, op)
        except ChallengeError as exc:
            raise ChallengeError(f"{where}: {exc}") from None
    return out


_BASE_DATA: dict[str, dict] = {}


def base_data(scenario_id: str) -> dict:
    """The bundled scenario as data. Read from the validated models, so it is exactly what the engine plays."""
    if scenario_id not in _BASE_DATA:
        scenario = load_bundled(scenario_id)
        _BASE_DATA[scenario_id] = {
            "public": scenario.public.model_dump(mode="json"),
            "private": scenario.private.model_dump(mode="json"),
        }
    return copy.deepcopy(_BASE_DATA[scenario_id])


def variant_data(manifest: dict, variant_id: str) -> dict:
    """The scenario file of a variant. Raises ChallengeError if the edits do not apply."""
    if variant_id not in manifest["variants"]:
        raise ChallengeError(f"unknown variant {variant_id!r}")
    variant = manifest["variants"][variant_id]
    try:
        data = apply_ops(base_data(variant["base"]), variant["ops"])
    except ChallengeError as exc:
        raise ChallengeError(f"variant {variant_id!r}: {exc}") from None
    # Its own identity: a variant is never mistaken for the case it was made from.
    data["public"]["id"] = f"{variant['base']}.{variant_id}"
    data["public"]["version"] = f"{data['public']['version']}+{variant_id}.{variant['revision']}"
    return data


_VARIANTS: dict[tuple[str, str], Scenario] = {}


def build_variant(manifest: dict, variant_id: str) -> Scenario:
    """A variant as a validated scenario: the ordinary models, then the ordinary lint."""
    data = variant_data(manifest, variant_id)
    key = (variant_id, json.dumps(data, sort_keys=True))
    if key not in _VARIANTS:
        try:
            scenario = Scenario(ScenarioPublic.model_validate(data["public"]), ScenarioPrivate.model_validate(data["private"]))
        except Exception as exc:  # pydantic's message names the field
            raise ChallengeError(f"variant {variant_id!r}: not a well-formed scenario: {exc}") from None
        problems = lint(scenario)
        if problems:
            raise ChallengeError(f"variant {variant_id!r}: rejected by the scenario lint:\n- " + "\n- ".join(problems))
        _VARIANTS[key] = scenario
    return _VARIANTS[key]


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


class Played:
    """One finished run and what the evaluation says about it."""

    def __init__(self, scenario: Scenario, engine: Engine, replay: dict | None) -> None:
        self.scenario = scenario
        self.engine = engine
        self.state = engine.state
        self.events = engine.events
        self.result = evaluate(scenario, engine.state, engine.events)
        self.replay = replay

    def false_statements(self, recipient: str | None = None) -> list[dict]:
        return [
            row for row in self.result["testimony"]["items"]
            if row["true"] is False and (recipient is None or row["recipient"] == recipient)
        ]


def _p_category_in(run: Played, among: list[str]) -> bool:
    return run.result["category"] in among


def _p_accused_not_in(run: Played, people: list[str]) -> bool:
    return run.result["accused"] not in people


def _p_culprit_is(run: Played, person: str) -> bool:
    return run.result["culprit"] == person


def _p_false_statements_made(run: Played, at_least: int, recipient: str | None = None) -> bool:
    return len(run.false_statements(recipient)) >= at_least


def _p_false_statement_unrefuted_at_close(run: Played, recipient: str | None = None) -> bool:
    return any(row["final_stance"] != "rejected" for row in run.false_statements(recipient))


def _p_no_false_statement_accepted_at_close(run: Played, recipient: str | None = None) -> bool | None:
    rows = run.false_statements(recipient)
    return None if not rows else all(row["final_stance"] != "accepted" for row in rows)


def _p_no_truthful_speaker_impeached(run: Played) -> bool | None:
    figure = run.result["testimony"]["truthful_speakers_impeached"]
    return None if figure["den"] == 0 else figure["num"] == 0


def _p_belief_support_at_most(run: Played, agent: str, proposition: str, most: int) -> bool:
    """Over the whole run, not only at its end: every recorded revision is looked at."""
    for event in run.events:
        if event.type == "BeliefsRevised" and event.data["agent"] == agent:
            entry = event.data["changes"].get(proposition)
            if entry is not None and entry["support"] > most:
                return False
    return True


def _p_holds(run: Played, agent: str, evidence: list[str], need: str = "all") -> bool:
    held = [e in run.state.agents[agent].holdings for e in evidence]
    return all(held) if need == "all" else any(held)


def _p_no_rejected_actions(run: Played) -> bool:
    return run.result["effort"]["rejected_actions"] == 0


def _p_replay_verifies(run: Played) -> bool | None:
    return None if run.replay is None else all(run.replay[level]["ok"] for level in REPLAY_LEVELS)


def _p_escalated(run: Played, expected: bool) -> bool:
    return bool(run.result["deception"]["escalations"]) == expected


def _p_voice_standing(run: Played, agent: str, voice: str, standing: str | None) -> bool:
    seen = run.state.agents[agent].credibility.get(voice)
    now = seen.current.standing if seen and seen.current else None
    return now == standing


PLAY_CHECKS: dict[str, Callable[..., bool | None]] = {
    "category_in": _p_category_in,
    "accused_not_in": _p_accused_not_in,
    "culprit_is": _p_culprit_is,
    "false_statements_made": _p_false_statements_made,
    "false_statement_unrefuted_at_close": _p_false_statement_unrefuted_at_close,
    "no_false_statement_accepted_at_close": _p_no_false_statement_accepted_at_close,
    "no_truthful_speaker_impeached": _p_no_truthful_speaker_impeached,
    "belief_support_at_most": _p_belief_support_at_most,
    "holds": _p_holds,
    "no_rejected_actions": _p_no_rejected_actions,
    "replay_verifies": _p_replay_verifies,
    "escalated": _p_escalated,
    "voice_standing": _p_voice_standing,
}


def _convicted(revision, suspects: Iterable[str]) -> str | None:
    met = [s for s in suspects if meets_standard(revision.suspects, s)]
    return met[0] if len(met) == 1 else None


def _status(revision, proposition: str) -> str:
    return revision.beliefs[proposition].status if proposition in revision.beliefs else "unknown"


def _r_convicted(fixture: dict, revision, person: str | None) -> bool:
    return _convicted(revision, fixture["world"]["suspects"]) == person


def _r_convicted_in(fixture: dict, revision, among: list) -> bool:
    return _convicted(revision, fixture["world"]["suspects"]) in among


def _r_status_in(fixture: dict, revision, proposition: str, among: list[str]) -> bool:
    return _status(revision, proposition) in among


def _r_support(fixture: dict, revision, proposition: str, exactly: int) -> bool:
    return proposition in revision.beliefs and revision.beliefs[proposition].support == exactly


def _r_standing(fixture: dict, revision, voice: str, standing: str | None) -> bool:
    return (revision.credibility[voice].standing if voice in revision.credibility else None) == standing


def _r_opportunity_in(fixture: dict, revision, suspect: str, among: list[str]) -> bool:
    return revision.suspects[suspect].opportunity in among


def _r_prime(fixture: dict, revision, person: str | None) -> bool:
    return revision.prime_suspect == person


def _r_order_independent(fixture: dict, revision) -> bool:
    """The conclusion does not depend on the order in which the items arrive."""
    items = reasoning_items(fixture)
    context = reasoning_context(fixture)
    reference = _reasoning_digest(revise(items, context))
    return all(_reasoning_digest(revise(variant, context)) == reference for variant in (items[::-1], items[1:] + items[:1]))


REASONING_CHECKS: dict[str, Callable[..., bool | None]] = {
    "convicted": _r_convicted,
    "convicted_in": _r_convicted_in,
    "status_in": _r_status_in,
    "support": _r_support,
    "standing": _r_standing,
    "opportunity_in": _r_opportunity_in,
    "prime": _r_prime,
    "order_independent": _r_order_independent,
}


def _evaluate_expectations(challenge: dict, checks: dict, *context: Any) -> dict[str, bool | None]:
    held: dict[str, bool | None] = {}
    for expectation in challenge["expectations"]:
        try:
            held[expectation["id"]] = checks[expectation["check"]](*context, **expectation.get("args", {}))
        except (KeyError, TypeError) as exc:
            raise ChallengeError(f"challenge {challenge['id']!r}, expectation {expectation['id']!r}: cannot be evaluated: {exc!r}") from None
    return held


def verdict(challenge: dict, held: dict[str, bool | None]) -> str:
    """What a run amounts to. The order matters: a broken contract or an unmet design
    condition says nothing about the reasoning, so those are named first."""
    failed = {kind: False for kind in KINDS}
    for expectation in challenge["expectations"]:
        if held[expectation["id"]] is False:
            failed[expectation["kind"]] = True
    if failed["contract"]:
        return "contract_violation"
    if failed["design"]:
        return "invalid_instance"
    return "falls_short" if failed["ideal"] else "meets_ideal"


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------


def play(scenario: Scenario, seed: int, policies: dict[str, str], schedule: list[tuple[int, str]]) -> Engine:
    """Run to completion through the ordinary engine, applying each intervention once its tick has finished."""
    engine = Engine.start(scenario, seed, policies)
    pending = sorted(schedule)
    while engine.state.status == "running":
        while pending and pending[0][0] <= engine.state.tick:
            engine.intervene(pending.pop(0)[1])
        engine.step()
    return engine


def challenge_setup(manifest: dict, challenge: dict, overrides: dict[str, str] | None = None) -> tuple[Scenario, dict[str, str], list[tuple[int, str]]]:
    scenario = build_variant(manifest, challenge["variant"])
    policies = {**challenge.get("policies", {}), **(overrides or {})}
    for agent_id in policies:
        if agent_id not in scenario.agents:
            raise ChallengeError(f"challenge {challenge['id']!r}: {agent_id!r} is not an agent of {scenario.id}")
    schedule = [(tick, name) for name, tick in challenge.get("interventions", [])]
    for _tick, name in schedule:
        if name not in scenario.interventions:
            raise ChallengeError(f"challenge {challenge['id']!r}: {scenario.id} has no intervention {name!r}")
    return scenario, policies, schedule


def run_playable(manifest: dict, challenge: dict, seed: int, replay: bool = False, overrides: dict[str, str] | None = None) -> tuple[dict, Played]:
    scenario, policies, schedule = challenge_setup(manifest, challenge, overrides)
    engine = play(scenario, seed, policies, schedule)
    run = Played(scenario, engine, verify_run(scenario, engine.events) if replay else None)
    held = _evaluate_expectations(challenge, PLAY_CHECKS, run)
    result = run.result
    accuser = result["lead"]
    row = {
        "seed": seed,
        "category": result["category"],
        "outcome": result["outcome"],
        "accused": result["accused"],
        "supported": result["accusation_supported"],
        "ticks": result["effort"]["ticks"],
        "actions": result["effort"]["actions"],
        "key_evidence": [result["evidence"]["key_discovered"]["num"], result["evidence"]["key_discovered"]["den"]],
        "key_evidence_held_by_accuser": [result["evidence"]["key_held_by_lead"]["num"], result["evidence"]["key_held_by_lead"]["den"]],
        "all_evidence": [result["evidence"]["all_discovered"]["num"], result["evidence"]["all_discovered"]["den"]],
        "contradictions_recognized": [result["contradictions"]["inherent_recognized_by_team"]["num"], result["contradictions"]["inherent_recognized_by_team"]["den"]],
        "contradictions_resolved_correctly": [result["contradictions"]["resolved_correctly"]["num"], result["contradictions"]["resolved_correctly"]["den"]],
        "statements": result["testimony"]["statements"],
        "false_statements": result["testimony"]["false"]["num"],
        "false_ever_accepted": result["testimony"]["false_ever_accepted"]["num"],
        "false_accepted_at_close": result["testimony"]["false_accepted_at_close"]["num"],
        "false_unrefuted_at_close": sum(1 for r in result["testimony"]["items"] if r["true"] is False and r["final_stance"] != "rejected"),
        "credibility_revisions": sum(1 for e in engine.events if e.type == "CredibilityRevised"),
        "impeached_by_accuser": sorted(
            voice for voice, seen in engine.state.agents[accuser].credibility.items() if seen.current and seen.current.standing == "impeached"
        ) if accuser else [],
        "withheld_answers": result["deception"]["answers_with_withholding"],
        "withholding_noticed": result["deception"]["noticed"]["num"],
        "escalations": len(result["deception"]["escalations"]),
        "rejected_actions": result["effort"]["rejected_actions"],
        "events": len(engine.events),
        "head": engine.state.head_hash,
        "replay": None if run.replay is None else {level: bool(run.replay[level]["ok"]) for level in REPLAY_LEVELS},
        "expectations": held,
        "verdict": verdict(challenge, held),
    }
    return row, run


def reasoning_items(fixture: dict) -> list[Item]:
    return [
        Item(
            id=item["id"], kind=item["kind"], speaker=item.get("speaker"), origin=item.get("origin"),
            asserts=tuple(Proposition.parse(text) for text in item["asserts"]),
        )
        for item in fixture["items"]
    ]


def reasoning_context(fixture: dict) -> ReasoningContext:
    world = fixture["world"]
    return ReasoningContext(
        zones=world["zones"], suspects=tuple(world["suspects"]), crime_location=world["crime_location"],
        crime_object=world["crime_object"], hearsay_weight=world.get("hearsay_weight", 1),
    )


def _reasoning_digest(revision) -> str:
    return json.dumps({
        "beliefs": {k: (b.support, b.contra, b.status) for k, b in sorted(revision.beliefs.items())},
        "suspects": {k: (a.score, a.opportunity, a.means, a.motive) for k, a in sorted(revision.suspects.items())},
        "prime": revision.prime_suspect,
        "credibility": {k: c.model_dump(mode="json") for k, c in sorted(revision.credibility.items())},
    }, sort_keys=True)


def run_reasoning(challenge: dict) -> dict:
    revision = revise(reasoning_items(challenge), reasoning_context(challenge))
    held = _evaluate_expectations(challenge, REASONING_CHECKS, challenge, revision)
    suspects = challenge["world"]["suspects"]
    convicted = _convicted(revision, suspects)
    culprit = challenge["culprit"]
    return {
        "convicted": convicted,
        # The same five labels, with the standard of proof standing in for an accusation.
        "category": "unresolved" if convicted is None else "correct_supported" if convicted == culprit else "wrong_supported",
        "prime_suspect": revision.prime_suspect,
        "beliefs": {key: {"support": b.support, "contra": b.contra, "status": b.status} for key, b in sorted(revision.beliefs.items())},
        "suspects": {s: {"score": a.score, "opportunity": a.opportunity, "means": a.means, "motive": a.motive} for s, a in sorted(revision.suspects.items())},
        "credibility": {voice: c.model_dump(mode="json") for voice, c in sorted(revision.credibility.items())},
        "expectations": held,
        "verdict": verdict(challenge, held),
    }


def median(values: list[int]) -> int | float | None:
    """The statistical median; a whole result stays an integer."""
    if not values:
        return None
    middle = statistics.median(values)
    return int(middle) if middle == int(middle) else middle


def _ratio(pairs: Iterable[list[int]]) -> list[int]:
    pairs = list(pairs)
    return [sum(p[0] for p in pairs), sum(p[1] for p in pairs)]


def _expectation_summary(challenge: dict, rows: list[dict]) -> list[dict]:
    summary = []
    for expectation in challenge["expectations"]:
        values = [row["expectations"][expectation["id"]] for row in rows]
        applicable = [v for v in values if v is not None]
        held = sum(1 for v in applicable if v)
        if not applicable:
            observed = "not_applicable"
        elif held == len(applicable):
            observed = "holds"
        elif held == 0:
            observed = "fails"
        else:
            observed = "mixed"
        summary.append({
            "id": expectation["id"], "kind": expectation["kind"], "says": expectation["says"],
            "held": held, "of": len(applicable), "predicted": expectation["predicted"], "observed": observed,
            "prediction_right": None if observed == "not_applicable" else observed == expectation["predicted"],
            "failed_seeds": [row["seed"] for row in rows if row["expectations"][expectation["id"]] is False] if rows and "seed" in rows[0] else [],
        })
    return summary


def aggregate_playable(challenge: dict, rows: list[dict]) -> dict:
    solved = [row["ticks"] for row in rows if row["outcome"] == "solved"]
    replayed = [row["replay"] for row in rows if row["replay"] is not None]
    return {
        "runs": len(rows),
        "categories": {name: sum(1 for row in rows if row["category"] == name) for name in CATEGORIES},
        "verdicts": {name: sum(1 for row in rows if row["verdict"] == name) for name in VERDICTS},
        "accused": dict(sorted(Counter(str(row["accused"]) for row in rows).items())),
        "false_accusations": sum(1 for row in rows if row["outcome"] == "wrong_accusation"),
        "median_ticks_when_solved": median(solved),
        "ticks_range_when_solved": [min(solved), max(solved)] if solved else None,
        "median_ticks": median([row["ticks"] for row in rows]),
        "median_actions": median([row["actions"] for row in rows]),
        "key_evidence_discovered": _ratio(row["key_evidence"] for row in rows),
        "key_evidence_held_by_accuser": _ratio(row["key_evidence_held_by_accuser"] for row in rows),
        "all_evidence_discovered": _ratio(row["all_evidence"] for row in rows),
        "contradictions_recognized": _ratio(row["contradictions_recognized"] for row in rows),
        "contradictions_resolved_correctly": _ratio(row["contradictions_resolved_correctly"] for row in rows),
        "statements": sum(row["statements"] for row in rows),
        "false_statements": sum(row["false_statements"] for row in rows),
        "false_ever_accepted": sum(row["false_ever_accepted"] for row in rows),
        "false_accepted_at_close": sum(row["false_accepted_at_close"] for row in rows),
        "false_unrefuted_at_close": sum(row["false_unrefuted_at_close"] for row in rows),
        "credibility_revisions": sum(row["credibility_revisions"] for row in rows),
        "runs_where_accuser_impeached_someone": sum(1 for row in rows if row["impeached_by_accuser"]),
        "withheld_answers": sum(row["withheld_answers"] for row in rows),
        "withholding_noticed": sum(row["withholding_noticed"] for row in rows),
        "runs_with_escalation": sum(1 for row in rows if row["escalations"]),
        "replay": {"verified": len(replayed), "passed": sum(1 for r in replayed if all(r.values())), "not_run": len(rows) - len(replayed)},
        "expectations": _expectation_summary(challenge, rows),
    }


def _definition(manifest: dict, challenge: dict, scenario: Scenario | None, policies: dict | None) -> dict:
    out = {key: challenge[key] for key in ("id", "kind", "category", "question", "culprit") if key in challenge}
    out["prediction"] = challenge.get("prediction")
    if scenario is not None:
        variant = manifest["variants"][challenge["variant"]]
        report = reach_report(scenario)
        out.update({
            "variant": challenge["variant"], "base": variant["base"], "scenario_id": scenario.id,
            "scenario_version": scenario.version, "scenario_hash": scenario.content_hash[:12],
            "policies": dict(sorted((policies or {}).items())),
            "interventions": challenge.get("interventions", []),
            "solvable": {accuser: entry["solvable"] for accuser, entry in sorted(report["accusers"].items())},
        })
    return out


def parse_seeds(text: str) -> list[int]:
    first, _, last = text.partition("-")
    return list(range(int(first), int(last or first) + 1))


def run_lab(
    manifest: dict,
    names: Iterable[str] = (),
    seeds: Iterable[int] = range(40),
    replay: str = "first",
    overrides: dict[str, str] | None = None,
    allow_drift: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Run the chosen challenges. `replay` is `every`, `first` (one seed per challenge) or `none`."""
    if replay not in ("every", "first", "none"):
        raise ChallengeError(f"replay must be every, first or none, not {replay!r}")
    check_manifest(manifest)  # a manifest handed over as data is checked as one loaded from a file
    drift = baseline_drift(manifest)
    if drift and not allow_drift:
        raise ChallengeError(
            "the build is not the one this manifest was registered against:\n- " + "\n- ".join(drift)
            + "\nResults would not be results of the registered experiment. Re-register the manifest, or pass allow_drift to run anyway and have the drift recorded."
        )
    seeds = list(seeds)
    chosen = select(manifest, names)
    results: dict[str, Any] = {
        "label": manifest["label"],
        "manifest_version": manifest["manifest_version"],
        "registered_against": manifest["frozen"],
        "running": current_baseline(manifest["frozen"]["scenarios"]),
        "drift": drift,
        "config": {"seeds": seeds, "replay": replay, "policy_overrides": dict(sorted((overrides or {}).items())), "registered_configuration": not overrides},
        "playable": {},
        "reasoning": {},
    }
    for challenge in chosen:
        if challenge["kind"] == "reasoning":
            row = run_reasoning(challenge)
            results["reasoning"][challenge["id"]] = {
                "definition": _definition(manifest, challenge, None, None),
                "result": row,
                "expectations": _expectation_summary(challenge, [row]),
            }
            if progress:
                progress(f"{challenge['id']}: {row['verdict']}")
            continue
        scenario, policies, _schedule = challenge_setup(manifest, challenge, overrides)
        rows = []
        for index, seed in enumerate(seeds):
            verify = replay == "every" or (replay == "first" and index == 0)
            row, _run = run_playable(manifest, challenge, seed, verify, overrides)
            rows.append(row)
        results["playable"][challenge["id"]] = {
            "definition": _definition(manifest, challenge, scenario, policies),
            "aggregate": aggregate_playable(challenge, rows),
            "runs": rows,
        }
        if progress:
            aggregate = results["playable"][challenge["id"]]["aggregate"]
            progress(f"{challenge['id']}: " + ", ".join(f"{name} {count}" for name, count in aggregate["categories"].items() if count))
    return results


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def _frac(pair: list[int]) -> str:
    return f"{pair[0]}/{pair[1]}"


def failed_cases(results: dict) -> list[dict]:
    """Every run that is not `meets_ideal`, with what it takes to run it again."""
    out = []
    overrides = results["config"]["policy_overrides"]
    flags = "".join(f" --policy {agent}={policy}" for agent, policy in overrides.items())
    for challenge_id, entry in results["playable"].items():
        names = {e["id"]: e for e in entry["aggregate"]["expectations"]}
        for row in entry["runs"]:
            if row["verdict"] != "meets_ideal":
                out.append({
                    "challenge": challenge_id, "seed": row["seed"], "verdict": row["verdict"], "category": row["category"],
                    "accused": row["accused"], "ticks": row["ticks"],
                    "failed": [f"{name} ({names[name]['kind']})" for name, held in row["expectations"].items() if held is False],
                    "reproduce": f"python -m caseforge lab reproduce {challenge_id} --seed {row['seed']}{flags}",
                })
    for challenge_id, entry in results["reasoning"].items():
        if entry["result"]["verdict"] != "meets_ideal":
            out.append({
                "challenge": challenge_id, "seed": None, "verdict": entry["result"]["verdict"], "category": entry["result"]["category"],
                "accused": entry["result"]["convicted"], "ticks": None,
                "failed": [f"{e['id']} ({e['kind']})" for e in entry["expectations"] if e["observed"] == "fails"],
                "reproduce": f"python -m caseforge lab reproduce {challenge_id}",
            })
    return out


def render_markdown(results: dict) -> str:
    lines: list[str] = []
    add = lines.append
    config, running = results["config"], results["running"]
    add("# Counterfactual laboratory: results")
    add("")
    add(f"> {results['label']}")
    add("")
    add(f"- Rule set `{running['rules_version']}`, engine version {running['engine_version']}, behaviour fingerprint `{running['behaviour_fingerprint']}`.")
    add("- Base scenarios: " + ", ".join(f"`{name}` {info['version']} (`{info['hash']}`)" for name, info in running["scenarios"].items()) + ".")
    seeds = config["seeds"]
    add(f"- Seeds {seeds[0]} to {seeds[-1]} ({len(seeds)} per playable challenge). Replay verification: {config['replay']}.")
    if results["drift"]:
        add("- **The build differs from the one the manifest was registered against:** " + "; ".join(results["drift"]) + ".")
    else:
        add("- The build is the one the manifest was registered against.")
    if not config["registered_configuration"]:
        add("- **Not the registered configuration:** policies overridden with " + ", ".join(f"{a}={p}" for a, p in config["policy_overrides"].items()) + ". Predictions do not apply.")
    add("")
    add("A run is `meets_ideal` when every expectation holds, `falls_short` when an *ideal* fails (a limit of")
    add("the policy or the reasoner, not a bug), `invalid_instance` when a *design* condition fails (the run does")
    add("not test what the challenge is about) and `contract_violation` when a *contract* fails (a software defect).")
    add("")

    if results["playable"]:
        add("## Playable challenges")
        add("")
        add("Each is a variant of a bundled scenario that passes the ordinary lint and is played by the ordinary engine.")
        add("")
        add("| Challenge | Category | Policies | Correct, supported | Correct, unsupported | Wrong, supported | Wrong, unsupported | Unresolved | Median ticks when solved | Meets ideal | Contract violations |")
        add("|---|---|---|---|---|---|---|---|---|---|---|")
        for challenge_id, entry in results["playable"].items():
            definition, aggregate = entry["definition"], entry["aggregate"]
            policies = ", ".join(f"{a}={p}" for a, p in definition["policies"].items()) or "baseline"
            cats = aggregate["categories"]
            median_ticks = "-" if aggregate["median_ticks_when_solved"] is None else aggregate["median_ticks_when_solved"]
            add(
                f"| `{challenge_id}` | {definition['category']} | {policies} | {cats['correct_supported']} | {cats['correct_unsupported']} | "
                f"{cats['wrong_supported']} | {cats['wrong_unsupported']} | {cats['unresolved']} | {median_ticks} | "
                f"{aggregate['verdicts']['meets_ideal']}/{aggregate['runs']} | {aggregate['verdicts']['contract_violation']} |"
            )
        add("")
        add("| Challenge | Key evidence found | Key evidence held by accuser | Contradictions recognised | Statements | False | False accepted at some point | False accepted at close | False not rejected at close | Credibility revisions | Replay passed |")
        add("|---|---|---|---|---|---|---|---|---|---|---|")
        for challenge_id, entry in results["playable"].items():
            a = entry["aggregate"]
            replay = f"{a['replay']['passed']}/{a['replay']['verified']}" if a["replay"]["verified"] else "not run"
            add(
                f"| `{challenge_id}` | {_frac(a['key_evidence_discovered'])} | {_frac(a['key_evidence_held_by_accuser'])} | {_frac(a['contradictions_recognized'])} | "
                f"{a['statements']} | {a['false_statements']} | {a['false_ever_accepted']} | {a['false_accepted_at_close']} | {a['false_unrefuted_at_close']} | "
                f"{a['credibility_revisions']} | {replay} |"
            )
        add("")
        for challenge_id, entry in results["playable"].items():
            definition, aggregate = entry["definition"], entry["aggregate"]
            add(f"### `{challenge_id}`")
            add("")
            add(f"{definition['question']}")
            add("")
            add(f"- Scenario `{definition['scenario_id']}` {definition['scenario_version']} (`{definition['scenario_hash']}`). Culprit: {definition['culprit']}. Lint: solvable {', '.join(f'{a}: {v}' for a, v in definition['solvable'].items())}.")
            if definition.get("prediction"):
                add(f"- Predicted beforehand: {definition['prediction']}")
            add(f"- Accused: {', '.join(f'{who} {count}' for who, count in aggregate['accused'].items())}.")
            add("")
            add("| Expectation | Kind | Held | Predicted | Observed | Prediction right |")
            add("|---|---|---|---|---|---|")
            for e in aggregate["expectations"]:
                right = "-" if e["prediction_right"] is None else "yes" if e["prediction_right"] else "**no**"
                add(f"| {e['says']} | {e['kind']} | {e['held']}/{e['of']} | {e['predicted']} | {e['observed']} | {right} |")
            add("")

    if results["reasoning"]:
        add("## Reasoning-only fixtures")
        add("")
        add("Items handed straight to the reasoner. No scenario, no agents, no acquisition: these say what the rules")
        add("conclude from given information and are not playable cases. They are not added to the table above.")
        add("")
        add("| Fixture | Category | Culprit | Standard met for | Verdict |")
        add("|---|---|---|---|---|")
        for challenge_id, entry in results["reasoning"].items():
            add(f"| `{challenge_id}` | {entry['definition']['category']} | {entry['definition']['culprit']} | {entry['result']['convicted'] or 'nobody'} | {entry['result']['verdict']} |")
        add("")
        for challenge_id, entry in results["reasoning"].items():
            add(f"### `{challenge_id}`")
            add("")
            add(entry["definition"]["question"])
            add("")
            if entry["definition"].get("prediction"):
                add(f"- Predicted beforehand: {entry['definition']['prediction']}")
                add("")
            add("| Expectation | Kind | Held | Predicted | Prediction right |")
            add("|---|---|---|---|---|")
            for e in entry["expectations"]:
                right = "-" if e["prediction_right"] is None else "yes" if e["prediction_right"] else "**no**"
                add(f"| {e['says']} | {e['kind']} | {'yes' if e['observed'] == 'holds' else 'no'} | {e['predicted']} | {right} |")
            add("")

    cases = failed_cases(results)
    add("## Runs that do not meet the ideal")
    add("")
    if not cases:
        add("None.")
    else:
        by_challenge: dict[str, list[dict]] = {}
        for case in cases:
            by_challenge.setdefault(case["challenge"], []).append(case)
        add("| Challenge | Runs | Verdicts | Seeds | Reproduce one |")
        add("|---|---|---|---|---|")
        for challenge_id, group in by_challenge.items():
            verdicts = ", ".join(f"{name} {count}" for name, count in sorted(Counter(c["verdict"] for c in group).items()))
            seeds_text = ", ".join(str(c["seed"]) for c in group if c["seed"] is not None) or "-"
            add(f"| `{challenge_id}` | {len(group)} | {verdicts} | {seeds_text} | `{group[0]['reproduce']}` |")
    add("")
    return "\n".join(lines)


def render_terminal(results: dict) -> str:
    lines = [results["label"]]
    running = results["running"]
    lines.append(f"rules {running['rules_version']}, engine {running['engine_version']}, fingerprint {running['behaviour_fingerprint']}"
                 + ("" if not results["drift"] else "   DRIFT: " + "; ".join(results["drift"])))
    if results["playable"]:
        lines.append("")
        lines.append(f"{'playable challenge':<34}{'runs':>5}{'c+s':>5}{'c-s':>5}{'w+s':>5}{'w-s':>5}{'unres':>6}{'median':>8}{'ideal':>7}{'contract':>9}{'replay':>8}")
        for challenge_id, entry in results["playable"].items():
            a = entry["aggregate"]
            c = a["categories"]
            med = "-" if a["median_ticks_when_solved"] is None else str(a["median_ticks_when_solved"])
            replay = f"{a['replay']['passed']}/{a['replay']['verified']}" if a["replay"]["verified"] else "-"
            lines.append(
                f"{challenge_id:<34}{a['runs']:>5}{c['correct_supported']:>5}{c['correct_unsupported']:>5}{c['wrong_supported']:>5}{c['wrong_unsupported']:>5}"
                f"{c['unresolved']:>6}{med:>8}{a['verdicts']['meets_ideal']:>7}{a['verdicts']['contract_violation']:>9}{replay:>8}"
            )
        lines.append("  c+s correct and supported, c-s correct but unsupported, w+s wrong but supported, w-s wrong and unsupported")
    if results["reasoning"]:
        lines.append("")
        lines.append(f"{'reasoning-only fixture':<34}{'standard met for':<18}{'culprit':<10}verdict")
        for challenge_id, entry in results["reasoning"].items():
            lines.append(f"{challenge_id:<34}{(entry['result']['convicted'] or 'nobody'):<18}{entry['definition']['culprit']:<10}{entry['result']['verdict']}")
    surprises = []
    for kind in ("playable", "reasoning"):
        for challenge_id, entry in results[kind].items():
            expectations = entry["aggregate"]["expectations"] if kind == "playable" else entry["expectations"]
            for e in expectations:
                if e["prediction_right"] is False:
                    surprises.append(f"  {challenge_id}: {e['id']} ({e['kind']}) predicted {e['predicted']}, observed {e['observed']} ({e['held']}/{e['of']})")
    lines.append("")
    lines.append("predictions that were wrong:" if surprises else "every prediction was right.")
    lines.extend(surprises)
    cases = failed_cases(results)
    lines.append("")
    lines.append(f"runs that do not meet the ideal: {len(cases)}")
    shown: set[str] = set()
    for case in cases:
        if case["challenge"] in shown:
            continue
        shown.add(case["challenge"])
        count = sum(1 for c in cases if c["challenge"] == case["challenge"])
        lines.append(f"  {case['challenge']}: {count}, e.g. {case['reproduce']}   [{case['verdict']}: {', '.join(case['failed'])}]")
    return "\n".join(lines)


def describe(manifest: dict, challenge: dict) -> str:
    """A challenge in words: what was changed, who did it, what is expected."""
    lines = [f"{challenge['id']}  ({challenge['kind']}, {challenge['category']})", "", challenge["question"], ""]
    if challenge["kind"] == "playable":
        variant = manifest["variants"][challenge["variant"]]
        scenario = build_variant(manifest, challenge["variant"])
        lines.append(f"variant {challenge['variant']} of {variant['base']}: {variant['summary']}")
        lines.append(f"scenario {scenario.id} {scenario.version}, hash {scenario.content_hash[:12]}, lint clean")
        lines.append("policies: " + (", ".join(f"{a}={p}" for a, p in sorted(challenge.get("policies", {}).items())) or "baseline"))
        if challenge.get("interventions"):
            lines.append("interventions: " + ", ".join(f"{name}@{tick}" for name, tick in challenge["interventions"]))
        lines.append("")
        lines.append("edits:" if variant["ops"] else "edits: none (the base scenario as it is)")
        for index, op in enumerate(variant["ops"], 1):
            target = op.get("id") or op.get("agent") or (op.get("record") or op.get("entity") or {}).get("id") or ""
            lines.append(f"  {index:>2}. {op['op']} {target}: {op['why']}")
    else:
        lines.append("items given to the reasoner:")
        for item in challenge["items"]:
            who = f" by {item['speaker']}" if item.get("speaker") else ""
            via = f" (passing on {item['origin']})" if item.get("origin") else ""
            lines.append(f"  {item['id']}: {item['kind']}{who}{via}: {', '.join(item['asserts'])}")
    lines.append("")
    lines.append(f"culprit: {challenge['culprit']}")
    if challenge.get("prediction"):
        lines.append(f"predicted beforehand: {challenge['prediction']}")
    lines.append("")
    lines.append("expectations:")
    for e in challenge["expectations"]:
        lines.append(f"  [{e['kind']:<8}] {e['says']}  (predicted: {e['predicted']})")
    return "\n".join(lines)
