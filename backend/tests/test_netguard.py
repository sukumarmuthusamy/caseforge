"""The local API answers only to loopback names, and no other site can change state through them.

Everything here runs against throwaway databases. Nothing is authentication: these tests pin what the guard
does, and the last ones state what it deliberately does not do.
"""

from __future__ import annotations

import http.client
import threading
import time

import pytest

from caseforge import netguard
from caseforge.__main__ import main
from caseforge.api import create_app
from caseforge.netguard import allowed_hosts, origin_host, parse_host
from caseforge.store import Store

from .conftest import SCENARIO_ID, SEED, LocalClient


@pytest.fixture()
def db(tmp_path):
    return tmp_path / "guard.sqlite3"


@pytest.fixture()
def client(db):
    with LocalClient(create_app(db)) as c:
        yield c


def new_run(client, **headers):
    response = client.post("/api/runs", json={"scenario_id": SCENARIO_ID, "seed": SEED}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


# -- parsing -----------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "value,expected",
    [
        ("localhost", "localhost"),
        ("LOCALHOST:8000", "localhost"),
        ("localhost.", "localhost"),
        ("127.0.0.1", "127.0.0.1"),
        ("127.0.0.1:8791", "127.0.0.1"),
        ("[::1]", "::1"),
        ("[::1]:8000", "::1"),
        ("caseforge.lan:80", "caseforge.lan"),
        ("", None),
        ("   ", None),
        ("::1", None),  # an IPv6 literal must be bracketed
        ("[::1", None),
        ("[::1]x", None),
        ("[::1]:", None),
        ("[::1]:80a", None),
        ("localhost:", None),
        ("localhost:port", None),
        ("localhost:8000:9", None),
        ("local host", None),
        ("localhost/x", None),
        ("user@localhost", None),
        ("localhost\x00.evil", None),
        ("-bad.example", None),
        ("a" * 300, None),
        ("[fe80::1%25eth0]", None),
    ],
)
def test_host_parsing(value, expected):
    assert parse_host(value) == expected


@pytest.mark.parametrize(
    "origin,expected",
    [
        ("http://localhost:5173", "localhost"),
        ("http://127.0.0.1:8000", "127.0.0.1"),
        ("https://[::1]:8000", "::1"),
        ("http://localhost", "localhost"),
        ("null", None),
        ("", None),
        ("file://localhost/x", None),
        ("http://user:pw@localhost", None),
        ("http://localhost/path", None),
        ("http://localhost?x=1", None),
        ("http://evil.example", "evil.example"),
    ],
)
def test_origin_parsing(origin, expected):
    assert origin_host(origin) == expected


def test_allow_list_trusts_loopback_and_only_what_was_named():
    assert allowed_hosts() == {"localhost", "127.0.0.1", "::1"}
    assert allowed_hosts("127.0.0.1") == {"localhost", "127.0.0.1", "::1"}
    assert allowed_hosts("192.168.1.20") == {"localhost", "127.0.0.1", "::1", "192.168.1.20"}
    assert allowed_hosts("::1", ["Box.LAN"]) == {"localhost", "127.0.0.1", "::1", "box.lan"}
    # A wildcard bind address is where the server listens, not a name a client may use.
    for wildcard in ("0.0.0.0", "::", "", "*"):
        assert allowed_hosts(wildcard) == {"localhost", "127.0.0.1", "::1"}
    assert allowed_hosts("0.0.0.0", ["box.lan"]) == {"localhost", "127.0.0.1", "::1", "box.lan"}
    for bad in ("*", "0.0.0.0", "a*b", "bad host", "http://x"):
        with pytest.raises(ValueError):
            allowed_hosts(None, [bad])


# -- Host --------------------------------------------------------------------------------------------

@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.1:8000", "localhost", "localhost:8791", "LocalHost:5173", "[::1]", "[::1]:8000"])
def test_loopback_hosts_are_answered(client, host):
    response = client.get("/api/health", headers={"Host": host})
    assert response.status_code == 200 and response.json()["ok"] is True


@pytest.mark.parametrize(
    "host",
    [
        "attacker.example",
        "attacker.example:8000",
        "127.0.0.1.attacker.example",  # a rebinding name that merely starts like loopback
        "localhost.attacker.example:8000",
        "attacker.example:8000@127.0.0.1",
        "127.0.0.2",
        "0.0.0.0",
        "0.0.0.0:8000",
        "[::]:8000",
        "::1",
        "[::1",
        "",
        "localhost, attacker.example",
    ],
)
def test_foreign_hosts_are_refused_with_a_clear_message(client, host):
    response = client.get("/api/runs", headers={"Host": host})
    assert response.status_code == 400
    assert "Invalid Host header" in response.json()["detail"] and "not authentication" in response.json()["detail"]


def test_a_request_with_a_foreign_host_never_reaches_a_route(client, db):
    """Read, create, step, reveal, delete and laboratory routes: every one is refused and nothing is stored or changed."""
    rid = new_run(client)
    before = client.get(f"/api/runs/{rid}").json()
    store_before = Store(db).load_events(rid)
    rebinding = {"Host": "attacker.example:8000"}

    assert client.get("/api/runs", headers=rebinding).status_code == 400
    assert client.get(f"/api/runs/{rid}/snapshot", headers=rebinding).status_code == 400
    assert client.get("/api/lab/challenges/control?reveal=true", headers=rebinding).status_code == 400
    assert client.post(f"/api/runs/{rid}/step", json={"ticks": 3}, headers=rebinding).status_code == 400
    assert client.post(f"/api/runs/{rid}/reveal", headers=rebinding).status_code == 400
    assert client.post("/api/runs", json={"scenario_id": SCENARIO_ID, "seed": 1}, headers=rebinding).status_code == 400
    assert client.post("/api/lab/challenges/control/open", json={"seed": 0}, headers=rebinding).status_code == 400
    assert client.post("/api/lab/challenges/control/execute", json={"seeds": [0]}, headers=rebinding).status_code == 400
    assert client.delete(f"/api/runs/{rid}", headers=rebinding).status_code == 400
    assert client.get("/", headers=rebinding).status_code == 400  # the built interface too

    assert client.get(f"/api/runs/{rid}").json() == before  # same tick, same hash, still not revealed
    assert Store(db).load_events(rid) == store_before
    assert [run["id"] for run in client.get("/api/runs").json()] == [rid]
    assert client.delete(f"/api/runs/{rid}").status_code == 204  # the same call with the right host works


def test_a_missing_or_repeated_host_header_is_refused(client):
    assert client.get("/api/health", headers={"Host": "127.0.0.1"}).status_code == 200
    scope_seen = []

    async def app(scope, receive, send):  # the middleware alone, driven directly
        scope_seen.append(scope)

    import asyncio

    guard = netguard.LocalRequestGuard(app)
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request"}

    for headers in ([], [(b"host", b"localhost"), (b"host", b"attacker.example")]):
        sent.clear()
        asyncio.run(guard({"type": "http", "method": "GET", "headers": headers, "path": "/"}, receive, send))
        assert sent[0]["status"] == 400
    assert scope_seen == []  # the application was never called


def test_websockets_are_not_accepted(client):
    import asyncio

    guard = netguard.LocalRequestGuard(lambda *a: None)
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    asyncio.run(guard({"type": "websocket", "headers": [(b"host", b"localhost")]}, None, send))
    assert sent == [{"type": "websocket.close", "code": 1008}]


# -- intentional non-loopback use -----------------------------------------------------------------------

def test_a_named_host_is_answered_and_nothing_else_is(db):
    with LocalClient(create_app(db, allowed_hosts=["caseforge.lan"])) as c:
        assert c.get("/api/health", headers={"Host": "caseforge.lan:8000"}).status_code == 200
        assert c.get("/api/health", headers={"Host": "127.0.0.1:8000"}).status_code == 200
        assert c.get("/api/health", headers={"Host": "other.lan:8000"}).status_code == 400
        assert c.get("/api/health", headers={"Host": "0.0.0.0:8000"}).status_code == 400


def test_the_environment_names_hosts_when_the_factory_is_called_by_uvicorn(db, monkeypatch):
    monkeypatch.setenv("CASEFORGE_ALLOWED_HOSTS", "box.lan, 10.0.0.5")
    with LocalClient(create_app(db)) as c:
        assert c.get("/api/health", headers={"Host": "box.lan"}).status_code == 200
        assert c.get("/api/health", headers={"Host": "10.0.0.5:8000"}).status_code == 200
        assert c.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_serve_does_not_trust_a_wildcard_bind_and_refuses_a_wildcard_allow(monkeypatch, capsys):
    import os

    import uvicorn

    seen = {}
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: seen.update(kwargs, allowed=os.environ.get("CASEFORGE_ALLOWED_HOSTS")))

    def serve(*argv):
        monkeypatch.delenv("CASEFORGE_ALLOWED_HOSTS", raising=False)  # one process serves once: start each case clean
        return main(["serve", *argv])

    assert serve("--host", "0.0.0.0") == 0
    assert seen["host"] == "0.0.0.0" and seen["allowed"] == ""  # listens everywhere, answers to loopback names only
    assert "does not authenticate" in capsys.readouterr().err

    assert serve("--host", "0.0.0.0", "--allow-host", "box.lan") == 0 and seen["allowed"] == "box.lan"
    assert serve("--host", "192.168.1.20") == 0 and seen["allowed"] == "192.168.1.20"
    assert serve() == 0 and seen["allowed"] == ""

    seen.clear()
    assert serve("--allow-host", "*") == 2
    assert "wildcard" in capsys.readouterr().err and not seen  # refused before anything started


# -- other sites, through an allowed loopback Host ------------------------------------------------------

CROSS_SITE = {"Origin": "https://attacker.example"}


def test_a_cross_site_post_is_refused_before_it_changes_anything(client, db):
    rid = new_run(client)
    before = client.get(f"/api/runs/{rid}").json()

    for origin in ("https://attacker.example", "http://127.0.0.1.attacker.example", "null", "file://", "http://localhost@attacker.example"):
        headers = {"Origin": origin}
        refused = [
            client.post(f"/api/runs/{rid}/reveal", headers=headers),  # no body: a plain cross-site form post can send this
            client.post(f"/api/runs/{rid}/step", json={"ticks": 5}, headers=headers),
            client.post("/api/runs", json={"scenario_id": SCENARIO_ID, "seed": 2}, headers=headers),
            client.post("/api/lab/challenges/control/open", json={"seed": 0}, headers=headers),
            client.post("/api/lab/challenges/control/execute", json={"seeds": [0]}, headers=headers),
            client.delete(f"/api/runs/{rid}", headers=headers),
            client.put(f"/api/runs/{rid}", headers=headers),
        ]
        assert [r.status_code for r in refused] == [403] * 7, origin
        assert "Cross-site request refused" in refused[0].json()["detail"]

    # A body with no content type at all, which a script can send without a preflight, is refused the same way.
    blob = client.post("/api/runs", content=b'{"scenario_id": "missing_prototype", "seed": 3}', headers=CROSS_SITE)
    assert blob.status_code == 403
    assert client.get(f"/api/runs/{rid}").json() == before
    assert Store(db).get_run(rid)["revealed"] == 0
    assert [run["id"] for run in client.get("/api/runs").json()] == [rid]


def test_the_interface_and_scripts_are_not_blocked(client):
    """The page's own requests, the Vite dev server's, and non-browser clients (no Origin) all work."""
    rid = new_run(client)
    for origin in ("http://127.0.0.1:8000", "http://localhost:8000", "http://localhost:5173", "http://[::1]:8000", "https://localhost"):
        step = client.post(f"/api/runs/{rid}/step", json={"ticks": 1}, headers={"Origin": origin})
        assert step.status_code == 200, origin
    assert client.post(f"/api/runs/{rid}/reveal").status_code == 200  # no Origin: curl, a script, this client
    assert client.get(f"/api/runs/{rid}", headers=CROSS_SITE).status_code == 200  # a read is not a state change...
    assert "access-control-allow-origin" not in {k.lower() for k in client.get("/api/runs", headers=CROSS_SITE).headers}  # ...and the browser will not hand it over
    assert client.options("/api/runs", headers={**CROSS_SITE, "Access-Control-Request-Method": "DELETE"}).headers.get("access-control-allow-origin") is None


def test_the_origin_check_follows_the_named_hosts(db):
    with LocalClient(create_app(db, allowed_hosts=["caseforge.lan"])) as c:
        assert c.post("/api/runs", json={"scenario_id": SCENARIO_ID}, headers={"Host": "caseforge.lan", "Origin": "http://caseforge.lan"}).status_code == 201
        assert c.post("/api/runs", json={"scenario_id": SCENARIO_ID}, headers={"Host": "caseforge.lan", "Origin": "http://attacker.example"}).status_code == 403


# -- through a real server ------------------------------------------------------------------------------

def test_a_real_uvicorn_server_enforces_it_too(db):
    """The same behaviour over an actual socket, with hand-written Host and Origin headers."""
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(create_app(db), host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.time() + 15
        while not server.started and time.time() < deadline:
            time.sleep(0.05)
        assert server.started
        port = server.servers[0].sockets[0].getsockname()[1]

        def call(method, path, headers=None, body=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
                for key, value in (headers or {"Host": f"127.0.0.1:{port}"}).items():
                    conn.putheader(key, value)
                if body is not None:
                    conn.putheader("Content-Type", "application/json")
                    conn.putheader("Content-Length", str(len(body)))
                conn.endheaders(body)
                response = conn.getresponse()
                return response.status, response.read()
            finally:
                conn.close()

        assert call("GET", "/api/health")[0] == 200
        assert call("GET", "/api/health", {"Host": f"localhost:{port}"})[0] == 200
        assert call("GET", "/api/health", {"Host": f"[::1]:{port}"})[0] == 200
        status, body = call("GET", "/api/runs", {"Host": f"attacker.example:{port}"})
        assert status == 400 and b"Invalid Host header" in body
        assert call("POST", "/api/runs", {"Host": f"attacker.example:{port}"}, b'{"seed": 1}')[0] == 400
        assert call("POST", "/api/runs", {"Host": f"127.0.0.1:{port}", "Origin": "https://attacker.example"}, b'{"seed": 1}')[0] == 403
        assert call("POST", "/api/runs", {"Host": f"127.0.0.1:{port}", "Origin": f"http://127.0.0.1:{port}"}, b'{"seed": 1}')[0] == 201
        assert len(Store(db).list_runs()) == 1  # only the legitimate one
    finally:
        server.should_exit = True
        thread.join(timeout=15)


def test_the_guard_is_not_authentication(client):
    """Stated so nobody reads more into it: a local process that sends an allowed Host and no Origin can do everything."""
    rid = new_run(client)
    assert client.post(f"/api/runs/{rid}/reveal").json()["revealed"] is True
    assert client.delete(f"/api/runs/{rid}").status_code == 204
