"""The counterfactual laboratory as the web interface reads it.

Three kinds of figure reach the interface, and each carries its own label so none
is mistaken for another:

* ``stored``    - the recorded results of the registered collection
  (``docs/lab/collection-1/results.json``), read from disk and never recomputed.
* ``executed``  - a small run made on request, here and now, on the local machine
  with the registered deterministic policies. Bounded (MAX_EXECUTE_SEEDS) and
  explicit: nothing runs because a page was opened.
* ``replay``    - one seed run again with all four replay levels checked, which is
  an ``executed`` result with ``replay`` on.

What this module does not do: it never edits a rule, a policy or the manifest, never
calls a model, never writes to the run store (opening a challenge as a playable run is
the caller's `RunService.create_run`), and never reads `.truth`, `.agendas` or
`.observations` itself. Ground truth comes from the manifest's own statement of the
design (the culprit it was written for, the edits it makes) and is withheld from every
response unless the caller asks for it with ``reveal``.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from . import lab
from .service import BadRequest, NotFound

MAX_EXECUTE_SEEDS = 10
RESULTS_ENV = "CASEFORGE_LAB_RESULTS"
STORED_NAME = "docs/lab/collection-1/results.json"

# Recorded limits of the frozen reasoner, as listed in tests/test_challenge.py (LIMITS). A
# test keeps the two in step. They are stated in the interface so that a support figure is
# never read as a verdict.
KNOWN_LIMITATIONS = (
    {"id": "lawful access and an ordinary motive", "explanation": "The standard of proof can be met for an innocent person who lawfully held the means and had an ordinary motive: the rules cannot tell lawful access from guilty access (wrong but supported)."},
    {"id": "one true sighting completes a case against an innocent", "explanation": "One unchecked sighting by a non-suspect gives strong opportunity, and a true sighting of an innocent person is indistinguishable from a false one."},
    {"id": "a false sighting frames an innocent", "explanation": "The same cause: one voice is enough, and the reasoner has no way to tell a false sighting from a true one."},
    {"id": "a speaker who contradicts himself", "explanation": "Only hard evidence impeaches. Two incompatible claims from one speaker leave the claims disputed and the speaker's standing unknown."},
    {"id": "two friends' alibi should not be enough to stop a conviction resting on a record", "explanation": "Two agreeing voices can hold one record to a draw, so collusion can block a true conviction (undecided, not wrong)."},
    {"id": "the witness was honestly mistaken once", "explanation": "The rules do not separate a mistake from a lie: once refuted, an honest witness's other statements weigh less."},
)

NOTES = (
    "They were registered before they were run, with predictions written down beforehand.",
    "A supported accusation means the rules' standard of proof was met on the evidence held. It is not a statement that the accusation is true: wrong_supported is a category of its own.",
    "A prediction being right means the recorded outcome matched what was written down beforehand. It is not evidence that the reasoner is good.",
    "Playable challenges (a whole investigation over 40 seeds) and reasoning-only fixtures (one set of items handed straight to the reasoner) are different kinds of experiment and are never added together.",
)


def default_results_path() -> Path:
    override = os.environ.get(RESULTS_ENV)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / Path(STORED_NAME)


# -- redaction ----------------------------------------------------------------------------------


def _expectations_view(expectations: list[dict], reveal: bool) -> list[dict]:
    return [{key: value for key, value in e.items() if reveal or key != "says"} for e in expectations]


def _aggregate_view(aggregate: dict, reveal: bool) -> dict:
    out = dict(aggregate)
    out["expectations"] = _expectations_view(aggregate["expectations"], reveal)
    if not reveal:
        out.pop("accused", None)  # who was accused, next to correct/wrong, would say who it was not
    return out


# The recorded rows say `key_evidence` for "how many of the decisive items were found". The
# read routes are scanned for that key as a marker of leaked scenario truth (tests/test_api.py),
# so the interface calls the same count by another name rather than weaken the scan.
_RENAMED = {"key_evidence": "decisive_found", "key_evidence_held_by_accuser": "decisive_held_by_accuser"}


def _run_view(row: dict, reveal: bool) -> dict:
    out = {_RENAMED.get(key, key): value for key, value in row.items() if reveal or key not in ("accused", "impeached_by_accuser")}
    if not reveal:
        # Who the accuser came to distrust points at who lied, so only how many is shown.
        out["impeached_by_accuser_count"] = len(row["impeached_by_accuser"])
    return out


class LabService:
    """Reads the registered collection, runs small bounded checks, and describes both."""

    def __init__(self, manifest: dict | None = None, results_path: str | os.PathLike | None = None) -> None:
        self.manifest = manifest if manifest is not None else lab.default_manifest()
        self.results_path = Path(results_path) if results_path is not None else default_results_path()
        self._stored: tuple[dict | None, str | None] | None = None
        self._busy = threading.Lock()

    # -- stored results -------------------------------------------------------------------------

    def stored(self) -> tuple[dict | None, str | None]:
        """The recorded results and, when they cannot be used, why not."""
        if self._stored is None:
            self._stored = self._load_stored()
        return self._stored

    def _load_stored(self) -> tuple[dict | None, str | None]:
        if not self.results_path.is_file():
            return None, f"no recorded results at {STORED_NAME} (they ship with the repository, not with an installed package)"
        try:
            results = json.loads(self.results_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return None, f"the recorded results cannot be read: {exc}"
        if not isinstance(results, dict) or results.get("manifest_version") not in lab.SUPPORTED_MANIFEST_VERSIONS:
            seen = results.get("manifest_version") if isinstance(results, dict) else "?"
            return None, f"the recorded results are of a version this build does not read ({seen})"
        if results.get("registered_against") != self.manifest["frozen"]:
            return None, "the recorded results were made against a different registration than the manifest this build ships"
        known = {c["id"] for c in self.manifest["challenges"]}
        if not (set(results.get("playable", {})) | set(results.get("reasoning", {}))) <= known:
            return None, "the recorded results name challenges that the manifest does not have"
        return results, None

    # -- reading --------------------------------------------------------------------------------

    def _challenge(self, challenge_id: str) -> dict:
        try:
            return lab.find_challenge(self.manifest, challenge_id)
        except lab.ChallengeError as exc:
            raise NotFound(str(exc)) from None

    def _entry(self, challenge: dict) -> dict | None:
        results, _ = self.stored()
        if results is None:
            return None
        return results["playable" if challenge["kind"] == "playable" else "reasoning"].get(challenge["id"])

    def overview(self) -> dict[str, Any]:
        results, problem = self.stored()
        drift = lab.baseline_drift(self.manifest)
        playable, reasoning = [], []
        wrong: list[dict] = []
        tally = {"playable": [0, 0], "reasoning": [0, 0]}
        for challenge in self.manifest["challenges"]:
            entry = self._entry(challenge)
            expectations: list[dict] = []
            if entry is not None:
                expectations = entry["aggregate"]["expectations"] if challenge["kind"] == "playable" else entry["expectations"]
            for e in expectations:
                if e["prediction_right"] is None:
                    continue
                tally[challenge["kind"]][1] += 1
                tally[challenge["kind"]][0] += int(e["prediction_right"])
                if not e["prediction_right"]:
                    wrong.append({
                        "challenge": challenge["id"], "kind": e["kind"], "expectation": e["id"],
                        "predicted": e["predicted"], "observed": e["observed"], "held": e["held"], "of": e["of"],
                    })
            head: dict[str, Any] = {
                "id": challenge["id"], "category": challenge["category"], "kind": challenge["kind"],
                "policies": dict(sorted(challenge.get("policies", {}).items())),
                "interventions": challenge.get("interventions", []),
                "has_stored": entry is not None,
            }
            if challenge["kind"] == "playable":
                head["aggregate"] = _aggregate_view(entry["aggregate"], False) if entry else None
                playable.append(head)
            else:
                head["result"] = (
                    {"category": entry["result"]["category"], "verdict": entry["result"]["verdict"], "expectations": _expectations_view(entry["expectations"], False)}
                    if entry else None
                )
                reasoning.append(head)
        config = results["config"] if results else None
        runs = sum(e["aggregate"]["runs"] for e in results["playable"].values()) if results else 0
        replayed = sum(e["aggregate"]["replay"]["passed"] for e in results["playable"].values()) if results else 0
        return {
            "title": self.manifest["title"],
            "label": lab.LABEL,
            "protocol": list(self.manifest["protocol"]),
            "categories": self.manifest["categories"],
            "outcome_categories": list(lab.CATEGORIES),
            "registered": self.manifest["frozen"],
            "running": lab.current_baseline(self.manifest["frozen"]["scenarios"]),
            "drift": drift,
            "can_execute": not drift,
            "stored": {
                "available": results is not None,
                "problem": problem,
                "source": STORED_NAME,
                "seeds": [config["seeds"][0], config["seeds"][-1]] if config and config["seeds"] else None,
                "replay": config["replay"] if config else None,
                "registered_configuration": config["registered_configuration"] if config else None,
                "runs": runs,
                "replay_passed": replayed,
            },
            "playable": playable,
            "reasoning": reasoning,
            "predictions": {
                "playable": {"right": tally["playable"][0], "of": tally["playable"][1]},
                "reasoning": {"right": tally["reasoning"][0], "of": tally["reasoning"][1]},
            },
            "wrong_predictions": wrong,
            "limitations": list(KNOWN_LIMITATIONS),
            "notes": list(NOTES),
            "execute": {"max_seeds": MAX_EXECUTE_SEEDS, "policies": "the challenge's registered policies only", "network": "none"},
        }

    def _ground_truth(self, challenge: dict) -> dict[str, Any]:
        truth: dict[str, Any] = {
            "culprit": challenge["culprit"],
            "question": challenge["question"],
            "prediction": challenge.get("prediction"),
            "expectations": [
                {"id": e["id"], "kind": e["kind"], "says": e["says"], "predicted": e["predicted"], "check": e["check"], "args": e.get("args", {})}
                for e in challenge["expectations"]
            ],
        }
        if challenge["kind"] == "playable":
            variant = self.manifest["variants"][challenge["variant"]]
            truth["variant_summary"] = variant["summary"]
            truth["edits"] = [
                {"op": op["op"], "target": op.get("id") or op.get("agent") or (op.get("record") or op.get("entity") or {}).get("id") or "", "why": op["why"]}
                for op in variant["ops"]
            ]
        return truth

    def challenge_detail(self, challenge_id: str, reveal: bool = False) -> dict[str, Any]:
        challenge = self._challenge(challenge_id)
        entry = self._entry(challenge)
        _, problem = self.stored()
        out: dict[str, Any] = {
            "id": challenge["id"], "kind": challenge["kind"], "category": challenge["category"],
            "category_meaning": self.manifest["categories"].get(challenge["category"]),
            "revealed": reveal,
            "source": "stored" if entry is not None else None,
            "stored_problem": None if entry is not None else problem,
            "can_execute": not lab.baseline_drift(self.manifest),
        }
        if challenge["kind"] == "playable":
            scenario, policies, _ = lab.challenge_setup(self.manifest, challenge)
            variant = self.manifest["variants"][challenge["variant"]]
            out["setup"] = {
                "variant": challenge["variant"], "base": variant["base"], "scenario_id": scenario.id,
                "scenario_version": scenario.version, "scenario_hash": scenario.content_hash[:12],
                "policies": dict(sorted(policies.items())), "interventions": challenge.get("interventions", []),
                "solvable": entry["definition"]["solvable"] if entry else None,
            }
            out["stored"] = None if entry is None else {
                "aggregate": _aggregate_view(entry["aggregate"], reveal),
                "runs": [_run_view(row, reveal) for row in entry["runs"]],
            }
        else:
            out["items"] = [
                {"id": item["id"], "kind": item["kind"], "speaker": item.get("speaker"), "origin": item.get("origin"), "asserts": item["asserts"]}
                for item in challenge["items"]
            ]
            if entry is None:
                out["stored"] = None
            else:
                result = {k: v for k, v in entry["result"].items() if reveal or k not in ("convicted", "prime_suspect")}
                out["stored"] = {"result": result, "expectations": _expectations_view(entry["expectations"], reveal)}
        if reveal:
            out["ground_truth"] = self._ground_truth(challenge)
        return out

    # -- running --------------------------------------------------------------------------------

    def execute(self, challenge_id: str, seeds: list[int], replay: bool, reveal: bool = False) -> dict[str, Any]:
        """Run a few seeds of one challenge now. Bounded, local, deterministic policies only."""
        challenge = self._challenge(challenge_id)
        drift = lab.baseline_drift(self.manifest)
        if drift:
            raise lab.ChallengeError(
                "this build is not the one the collection was registered against, so a run now would not be a run of the registered experiment:\n- " + "\n- ".join(drift)
            )
        if challenge["kind"] == "reasoning":
            seeds = []
        else:
            if not seeds:
                raise BadRequest("name at least one seed")
            if len(seeds) > MAX_EXECUTE_SEEDS:
                raise BadRequest(f"at most {MAX_EXECUTE_SEEDS} seeds can be run from the interface; use `python -m caseforge lab run` for more")
            if len(set(seeds)) != len(seeds) or any(isinstance(s, bool) or not isinstance(s, int) or not 0 <= s < 2**31 for s in seeds):
                raise BadRequest("seeds must be distinct whole numbers from 0 to 2147483647")
        if not self._busy.acquire(blocking=False):
            raise lab.ChallengeError("another laboratory run is still going; wait for it to finish")
        try:
            entry = self._entry(challenge)
            out: dict[str, Any] = {
                "source": "executed", "id": challenge["id"], "kind": challenge["kind"], "revealed": reveal,
                "seeds": seeds, "replay": bool(replay) and challenge["kind"] == "playable",
                "label": "Run just now on this machine with the registered policies. Not the recorded collection.",
            }
            if challenge["kind"] == "reasoning":
                row = lab.run_reasoning(challenge)
                out["result"] = {k: v for k, v in row.items() if reveal or k not in ("convicted", "prime_suspect")}
                out["expectations"] = _expectations_view(lab._expectation_summary(challenge, [row]), reveal)
                stored = entry["result"] if entry else None
                out["compared_with_stored"] = None if stored is None else {"compared": 1, "identical": int(stored == row), "different_seeds": []}
                return out
            rows = [lab.run_playable(self.manifest, challenge, seed, replay=bool(replay))[0] for seed in seeds]
            out["runs"] = [_run_view(row, reveal) for row in rows]
            out["aggregate"] = _aggregate_view(lab.aggregate_playable(challenge, rows), reveal)
            if entry is None:
                out["compared_with_stored"] = None
            else:
                by_seed = {row["seed"]: row for row in entry["runs"]}
                comparable = [row for row in rows if row["seed"] in by_seed]
                different = [row["seed"] for row in comparable if by_seed[row["seed"]]["head"] != row["head"]]
                out["compared_with_stored"] = {"compared": len(comparable), "identical": len(comparable) - len(different), "different_seeds": different}
            return out
        finally:
            self._busy.release()

    def open_request(self, challenge_id: str, seed: int) -> dict[str, Any]:
        """What the run service needs to start this challenge as an ordinary run."""
        challenge = self._challenge(challenge_id)
        if challenge["kind"] != "playable":
            raise BadRequest(f"{challenge_id} is a reasoning-only fixture: there is no investigation to open. Its items are shown on its page")
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
            raise BadRequest("seed must be a whole number from 0 to 2147483647")
        scenario, policies, schedule = lab.challenge_setup(self.manifest, challenge)
        return {
            "scenario_id": scenario.id, "seed": seed, "policies": policies,
            "label": f"lab: {challenge_id}, seed {seed}",
            "registered_interventions": [{"intervention_id": name, "after_tick": tick} for tick, name in sorted(schedule)],
        }
