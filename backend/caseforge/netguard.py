"""Who may talk to the local API: Host-header validation and a cross-site check for state changes.

CaseForge has no accounts. What it promises instead is that it is a local tool, and binding to 127.0.0.1
only keeps other machines out, not the user's own browser: a web page can make a name it controls resolve
to 127.0.0.1 (DNS rebinding) and then, being "same origin" with that name, read every run, reveal solutions
and delete runs. Two small checks close that, both applied before any route runs:

* **Host.** Only `localhost`, `127.0.0.1` and `::1` are answered to, plus names the operator listed
  explicitly. A wildcard bind address (`0.0.0.0`, `::`) is not a name and trusts nothing extra.
* **Origin on unsafe methods.** A request that changes state (POST, PUT, PATCH, DELETE) and carries an
  `Origin` header must come from one of the same names. Browsers always send `Origin` on a cross-site
  form post or `fetch`, so another website cannot trigger an action even through the allowed loopback
  name. A request with no `Origin` (curl, a script, the test client) is not a browser request and is let through.

This is a guard against browsers being turned on the user, not authentication: anything that can reach the
port and sets its own `Host` can still use the API. Ports are not compared; another web server on this same
machine (any port of `localhost`) is not isolated from CaseForge by this check.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from urllib.parse import urlsplit

LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")
WILDCARD_BINDS = ("", "*", "0.0.0.0", "::")
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_NAME = re.compile(r"^[a-z0-9]([a-z0-9._-]*[a-z0-9])?$")
_IPV6 = re.compile(r"^[0-9a-f:.]+$")
_PORT = re.compile(r"^[0-9]{1,5}$")


def parse_host(value: str) -> str | None:
    """The host name of a `Host` header value (or an Origin's authority), lower-cased, without port or brackets.

    None for anything that is not a well-formed `name`, `name:port`, `[v6]` or `[v6]:port`.
    """
    value = value.strip().lower()
    if not value or len(value) > 255:
        return None
    if value.startswith("["):
        end = value.find("]")
        if end < 0:
            return None
        name, rest = value[1:end], value[end + 1 :]
        if (rest and not (rest.startswith(":") and _PORT.match(rest[1:]))) or ":" not in name or not _IPV6.match(name):
            return None
        return name
    if value.count(":") > 1:  # an IPv6 literal must be bracketed in a Host header
        return None
    name, _, port = value.partition(":")
    if (":" in value and not _PORT.match(port)) or not name:
        return None
    name = name.removesuffix(".")
    return name if _NAME.match(name) else None


def normalize_allowed(name: str) -> str:
    """One entry of an allow list, as `parse_host` would return it. ValueError for a wildcard or malformed entry."""
    cleaned = name.strip().lower().removeprefix("[").removesuffix("]")
    if cleaned in WILDCARD_BINDS or "*" in cleaned:
        raise ValueError(f"{name!r} is a wildcard: name the hosts to allow, never all of them")
    parsed = parse_host(f"[{cleaned}]" if ":" in cleaned else cleaned)
    if parsed is None:
        raise ValueError(f"{name!r} is not a host name or address")
    return parsed


def allowed_hosts(bind_host: str | None = None, extra: Iterable[str] = ()) -> frozenset[str]:
    """Loopback names, the host the server was deliberately bound to (unless that is a wildcard), and `extra`."""
    names = set(LOOPBACK_HOSTS)
    if bind_host is not None and bind_host.strip().lower() not in WILDCARD_BINDS:
        names.add(normalize_allowed(bind_host))
    names.update(normalize_allowed(item) for item in extra if item.strip())
    return frozenset(names)


def hosts_from_env(value: str | None) -> list[str]:
    return [item for item in (value or "").split(",") if item.strip()]


def origin_host(origin: str) -> str | None:
    """The host of an `Origin` header, or None for `null`, a non-http scheme, credentials or garbage."""
    try:
        parts = urlsplit(origin.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or "@" in parts.netloc or parts.path not in ("", "/") or parts.query or parts.fragment:
        return None
    return parse_host(parts.netloc)


def _shown(value: str) -> str:
    return repr(value[:60] + ("..." if len(value) > 60 else ""))


class LocalRequestGuard:
    """Pure ASGI middleware: refuse a foreign Host, and a state-changing request from a foreign Origin."""

    def __init__(self, app, allowed: Iterable[str] = LOOPBACK_HOSTS) -> None:
        self.app = app
        self.allowed = frozenset(allowed)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers: dict[str, list[str]] = {}
        for key, value in scope.get("headers", []):
            headers.setdefault(key.decode("latin-1").lower(), []).append(value.decode("latin-1"))

        hosts = headers.get("host", [])
        host = parse_host(hosts[0]) if len(hosts) == 1 else None
        if host is None or host not in self.allowed:
            shown = _shown(hosts[0]) if len(hosts) == 1 else "missing or repeated"
            await self._refuse(
                send, 400,
                f"Invalid Host header ({shown}). CaseForge answers only to {', '.join(sorted(self.allowed))}. "
                "This protects against DNS rebinding; it is not authentication. To serve under another name, start it with --allow-host.",
            )
            return

        if scope["method"] in UNSAFE_METHODS and "origin" in headers:
            origin = origin_host(headers["origin"][0]) if len(headers["origin"]) == 1 else None
            if origin is None or origin not in self.allowed:
                await self._refuse(
                    send, 403,
                    f"Cross-site request refused (Origin {_shown(headers['origin'][0])}): a page from another site may not change CaseForge state.",
                )
                return

        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(send, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode()
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
