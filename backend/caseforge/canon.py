"""Canonical serialization, hashing and deterministic choice.

Everything that can influence the event log goes through this module, so the
log is byte-identical across processes, platforms and Python versions.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Sequence, TypeVar

T = TypeVar("T")

GENESIS_HASH = "0" * 64


def canonical_json(obj: Any) -> str:
    """Stable JSON: sorted keys, no whitespace, ASCII only.

    Floats are rejected on purpose. Integer-only payloads remove any question
    of float formatting differences between platforms.
    """
    _reject_floats(obj)
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _reject_floats(obj: Any) -> None:
    if isinstance(obj, float):
        raise TypeError("floats are not allowed in canonical payloads")
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise TypeError(f"non-string key in canonical payload: {key!r}")
            _reject_floats(value)
    elif isinstance(obj, (list, tuple)):
        for value in obj:
            _reject_floats(value)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chain_hash(prev_hash: str, body: dict[str, Any]) -> str:
    """Hash of one event given the hash of its predecessor."""
    return sha256_hex(prev_hash + canonical_json(body))


class DeterministicRng:
    """Counter-based randomness derived from a hash.

    There is no hidden generator state: a value depends only on the seed, the
    context it was created with and the order of calls. That makes branching
    trivial (nothing to snapshot) and avoids relying on `random` internals,
    which are not guaranteed stable across Python versions.
    """

    def __init__(self, seed: int, *context: Any) -> None:
        self._key = "|".join([str(seed), *[str(part) for part in context]])
        self._calls = 0

    def _next(self, label: str = "") -> int:
        self._calls += 1
        digest = hashlib.sha256(f"{self._key}|{self._calls}|{label}".encode("utf-8")).digest()
        return int.from_bytes(digest[:8], "big")

    def pick(self, items: Sequence[T]) -> T:
        """Choose one element. The caller must pass a deterministically ordered sequence."""
        if not items:
            raise ValueError("cannot pick from an empty sequence")
        return items[self._next("pick") % len(items)]

    def shuffled(self, items: Iterable[str]) -> list[str]:
        """Order string ids by a keyed hash. Independent of input order."""
        self._calls += 1
        salt = f"{self._key}|{self._calls}|shuffle"
        return sorted(items, key=lambda item: hashlib.sha256(f"{salt}|{item}".encode("utf-8")).hexdigest())
