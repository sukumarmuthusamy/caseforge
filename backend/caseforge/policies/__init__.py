"""Policy registry. A run stores policy *names*; instances are built on demand."""

from __future__ import annotations

from .base import Policy, describe, legal_actions
from .baseline import BaselinePolicy

POLICY_INFO = {
    "baseline": "Deterministic rule-based investigator. Hears the accused before naming them.",
    "hasty": "Baseline without due diligence: accuses as soon as the standard is met, publishes one point earlier.",
    "deceptive": "Baseline with a private agenda from the scenario: quietly withholds records naming the person it protects and leaks records against someone else. Same as baseline for an agent without an agenda.",
    "llm": "Model-backed action selection. Requires explicit opt-in through environment variables.",
}


def make_policy(name: str) -> Policy:
    if name == "baseline":
        return BaselinePolicy()
    if name == "hasty":
        return BaselinePolicy(name="hasty", diligent=False)
    if name == "deceptive":
        from .deceptive import DeceptivePolicy

        return DeceptivePolicy()
    if name == "llm":
        from .llm import LLMPolicy

        return LLMPolicy.from_env()
    raise KeyError(f"unknown policy: {name}")


__all__ = ["Policy", "BaselinePolicy", "POLICY_INFO", "make_policy", "legal_actions", "describe"]
