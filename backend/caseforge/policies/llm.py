"""Optional model-backed policy.

Off by default. Nothing in this module runs unless a run assigns the "llm"
policy to an agent *and* the environment opts in:

    CASEFORGE_LLM_ENABLED=1
    CASEFORGE_LLM_BASE_URL=https://.../v1      (any OpenAI-compatible endpoint)
    CASEFORGE_LLM_MODEL=<model name>
    CASEFORGE_LLM_API_KEY=<key>                (optional, e.g. for local Ollama)
    CASEFORGE_LLM_MAX_CALLS=200                (budget for the whole server process)

The call budget is one counter for the process, shared by every run, branch
and rebuilt engine: see `CallBudget`. Every attempted request is charged,
retries included. Restarting the process starts a new budget; the counter is
deliberately not persisted, so a restart is the explicit way to renew it.

The model never writes state. It picks one entry from a menu of legal actions
that the engine enumerated, the reply is validated against a strict schema,
and the engine validates the chosen action again. On any failure the baseline
policy decides instead, and the failure is recorded in the decision trace.
Replay reads recorded decisions and never calls a model.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError

from ..canon import DeterministicRng, canonical_json, sha256_hex
from ..models import AgentView, Decision, DecisionTrace
from .base import describe, legal_actions
from .baseline import BaselinePolicy


class LLMDisabled(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    api_key: str | None = None
    timeout_seconds: int = 30
    max_retries: int = 2
    max_tokens: int = 300
    max_calls: int = 200

    @classmethod
    def from_env(cls) -> "LLMConfig":
        if os.environ.get("CASEFORGE_LLM_ENABLED") != "1":
            raise LLMDisabled("LLM policies are off. Set CASEFORGE_LLM_ENABLED=1 together with CASEFORGE_LLM_BASE_URL and CASEFORGE_LLM_MODEL to opt in.")
        base_url = os.environ.get("CASEFORGE_LLM_BASE_URL", "").rstrip("/")
        model = os.environ.get("CASEFORGE_LLM_MODEL", "")
        if not base_url or not model:
            raise LLMDisabled("CASEFORGE_LLM_BASE_URL and CASEFORGE_LLM_MODEL must both be set.")
        return cls(
            base_url=base_url,
            model=model,
            api_key=os.environ.get("CASEFORGE_LLM_API_KEY") or None,
            max_calls=int(os.environ.get("CASEFORGE_LLM_MAX_CALLS", "200")),
        )


class CallBudget:
    """Counts attempted model requests across every policy that shares it.

    A policy asks before each request; the answer is no once `limit` requests
    have been charged. The limit is passed in by the caller so the configured
    value always governs, while the spend survives any number of policy,
    engine or run lifetimes. Safe to use from several threads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spent = 0

    @property
    def spent(self) -> int:
        with self._lock:
            return self._spent

    def try_spend(self, limit: int) -> bool:
        with self._lock:
            if self._spent >= limit:
                return False
            self._spent += 1
            return True

    def reset(self) -> None:
        with self._lock:
            self._spent = 0


# The default for every LLMPolicy: one budget per interpreter. A policy built
# without an explicit budget can therefore never widen the allowance.
PROCESS_BUDGET = CallBudget()


class ChatClient(Protocol):
    def complete(self, messages: list[dict[str, str]], config: LLMConfig) -> dict[str, Any]:
        """Return {"text": str, "usage": dict | None}. May raise on transport errors."""
        ...


class OpenAICompatibleClient:
    """Minimal chat-completions client on the standard library."""

    def complete(self, messages: list[dict[str, str]], config: LLMConfig) -> dict[str, Any]:
        body = json.dumps({
            "model": config.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": config.max_tokens,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        request = urllib.request.Request(f"{config.base_url}/chat/completions", data=body, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {"text": payload["choices"][0]["message"]["content"], "usage": payload.get("usage")}


class LLMChoice(BaseModel):
    """The only shape a model reply may take."""

    model_config = ConfigDict(extra="forbid")

    choice: StrictInt
    rationale: str = Field(default="", max_length=600)


def parse_choice(text: str, menu_size: int) -> LLMChoice:
    """Extract and validate a reply. Raises ValueError with a short reason."""
    if not isinstance(text, str):
        raise ValueError("reply is not text")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in reply")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc.msg}") from exc
    try:
        choice = LLMChoice.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ValueError(f"schema violation at {'.'.join(str(p) for p in first['loc']) or 'root'}: {first['msg']}") from exc
    if not 0 <= choice.choice < menu_size:
        raise ValueError(f"choice {choice.choice} is outside the menu (0..{menu_size - 1})")
    return choice


SYSTEM_PROMPT = (
    "You are playing one investigator in a simulated mystery. You see only what your character has "
    "legitimately learned. Choose exactly one action from the numbered menu. Prefer actions that resolve "
    "uncertainty about the leading suspects. Do not accuse or publish unless opportunity, means and motive "
    "are each supported by evidence you hold. Reply with JSON only: "
    '{"choice": <menu number>, "rationale": "<one sentence naming the evidence ids you relied on>"}'
)


def build_messages(view: AgentView, actions: list) -> list[dict[str, str]]:
    briefing = {
        "you": {"id": view.me.id, "name": view.me.name, "role": view.me.role, "goals": list(view.me.goals)},
        "tick": view.tick,
        "max_ticks": view.case.max_ticks,
        "case": view.case.briefing,
        "suspects": {
            name: {"score": a.score, "opportunity": a.opportunity, "means": a.means, "motive": a.motive}
            for name, a in view.suspects.items()
        },
        "prime_suspect": view.prime_suspect,
        "beliefs": {key: f"{b.status} (+{b.support}/-{b.contra})" for key, b in view.beliefs.items()},
        "evidence": [{"id": e.id, "kind": e.kind, "title": e.title, "text": e.text} for e in view.evidence],
        "public_claims": [{"id": c.id, "by": c.by, "says": c.proposition, "status": c.status} for c in view.claims],
        "requests_waiting_for_you": [{"id": r.id, "from": r.sender, "topic": r.topic, "source": r.source} for r in view.inbox],
    }
    menu = "\n".join(f"{index}: {describe(action)}" for index, action in enumerate(actions))
    user = f"What you know:\n{json.dumps(briefing, indent=1)}\n\nMenu:\n{menu}\n\nReply with JSON only."
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _safe_usage(usage: Any) -> dict[str, int] | None:
    """Keep integer token counts only: floats are not allowed in the event log."""
    if not isinstance(usage, dict):
        return None
    kept = {k: v for k, v in usage.items() if isinstance(v, int) and not isinstance(v, bool)}
    return kept or None


class LLMPolicy:
    name = "llm"
    deterministic = False

    def __init__(
        self,
        client: ChatClient,
        config: LLMConfig,
        fallback: BaselinePolicy | None = None,
        budget: CallBudget | None = None,
    ) -> None:
        self.client = client
        self.config = config
        self.fallback = fallback or BaselinePolicy()
        self.budget = budget if budget is not None else PROCESS_BUDGET

    @classmethod
    def from_env(cls) -> "LLMPolicy":
        return cls(OpenAICompatibleClient(), LLMConfig.from_env())

    def decide(self, view: AgentView, rng: DeterministicRng) -> Decision:
        actions = legal_actions(view)
        messages = build_messages(view, actions)
        record: dict[str, Any] = {
            "model": self.config.model,
            "prompt_sha256": sha256_hex(canonical_json(messages)),
            "menu_size": len(actions),
            "attempts": [],
        }
        for _ in range(1 + self.config.max_retries):
            if not self.budget.try_spend(self.config.max_calls):
                record["attempts"].append({"error": "call budget exhausted"})
                break
            try:
                reply = self.client.complete(messages, self.config)
                text = reply.get("text") if isinstance(reply, dict) else None
            except (urllib.error.URLError, TimeoutError, OSError, KeyError, ValueError) as exc:
                record["attempts"].append({"error": f"transport: {type(exc).__name__}"})
                continue
            try:
                choice = parse_choice(text, len(actions))
            except ValueError as exc:
                record["attempts"].append({"error": str(exc)[:200], "raw": str(text)[:200]})
                continue
            record["attempts"].append({"ok": True})
            record.update({"choice": choice.choice, "fallback": False, "usage": _safe_usage(reply.get("usage"))})
            return Decision(
                action=actions[choice.choice],
                trace=DecisionTrace(policy=self.name, reason=choice.rationale or "model gave no rationale", llm=record),
            )
        decision = self.fallback.decide(view, rng)
        record["fallback"] = True
        return Decision(
            action=decision.action,
            trace=DecisionTrace(
                policy=self.name,
                reason=f"model output unusable, baseline decided: {decision.trace.reason}",
                refs=decision.trace.refs,
                considered=decision.trace.considered,
                llm=record,
            ),
        )
