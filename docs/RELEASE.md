# Release status

CaseForge is at version `1.0.0rc1` (npm `1.0.0-rc.1`, proposed tag `v1.0.0-rc.1`), a first release
candidate. See [CHANGELOG.md](../CHANGELOG.md). This page records what has actually been run, and on what.
Passing tests are not the same thing as a release, so the two are kept apart here.

## What has been verified

The local checks below were run on Windows 11. The hosted checks are in the next table.

| Check | How | Result |
|---|---|---|
| Backend tests | `pytest` | 658 passed and 6 strict expected failures on Python 3.11.16, 3.12.14 and 3.13.2 |
| Clean install | the source tree exported with `git archive` into an empty directory, a new virtual environment, fresh dependencies from PyPI | `pip install -e ".[dev]"` works on 3.12 and 3.13; a non-editable wheel builds and installs on 3.11.16 and 3.13.2. Resolved versions: FastAPI 0.163.1, pydantic 2.14.3, uvicorn 0.54.0, Starlette 1.10.0, httpx 0.28.1, pytest 9.2.0 |
| CLI on a clean install | `caseforge --help`, `validate`, `lab check`, `demo --seed 7`, `lab reproduce control --seed 0` | pass; `demo --seed 7` gives the same head hash (`57b483e5...`) on every Python version tried |
| Frontend | `npm ci`, `npm run typecheck`, `npm run build` | pass on Node 22.23.5 and 24.14 |
| Browser tests | `npm run e2e` against the real server | 32 passed on Microsoft Edge |
| Local API guard | `tests/test_netguard.py` (68 cases, one of them over a real uvicorn socket) and `e2e/local-api.spec.ts` (a page of another site in a real browser) | pass; the browser test fails when the guard is removed |
| Documented sweeps | all 720 head hashes in the README tables recompared after the stored-run compatibility change (DECISIONS D25) | identical. Later changes left the pinned runs in `tests/test_pinned_runs.py` and the recorded laboratory results in `tests/test_lab_results.py` unchanged |

### Hosted CI (GitHub Actions, Ubuntu)

Run `43847562623` on `main` passed all four jobs.

| Job | Result |
|---|---|
| backend, Python 3.11 | 658 passed, 6 strict expected failures; scenario lint, `lab check`, `demo --seed 7` and `lab reproduce control --seed 0` pass |
| backend, Python 3.13 | the same |
| frontend, Node 22 | `npm ci`, `npm run typecheck` and `npm run build` pass |
| browser, Chrome | 32 passed |

The pinned runs and the recorded laboratory results are asserted by the test suite, so they reproduce on
Linux as well as on Windows.

Starlette warns that its test client will want `httpx2` in a future version. That is a deprecation
warning, not a failure.

## Not verified

- macOS.
- Linux other than the Ubuntu runner image, and Windows other than the one machine used here.
- Python 3.12 in CI. It was tested locally only; the CI matrix is 3.11 and 3.13.
- Firefox and Safari. The browser tests ran on Edge locally and on Chrome in CI.
- Node 20, and Node 24 in CI (24 was tried locally).
- A real model behind the opt-in `llm` policy. Tests use a stub and never touch a network.
- Accessibility. Colour is paired with text in the outcome bars, but keyboard paths and screen-reader
  labels have not been reviewed beyond what Playwright's role queries imply.

## Continuous integration

`.github/workflows/ci.yml` uses free GitHub-hosted runners, needs no secrets or paid services, forces the
model-backed agents off, and keeps every job short.

- **backend** (Ubuntu, Python 3.11 and 3.13): `pytest`, `caseforge validate`, `caseforge lab check`, a
  narrated `demo`, and one recorded laboratory run reproduced from its seed.
- **frontend** (Ubuntu, Node 22): `npm ci`, `npm run typecheck`, `npm run build`.
- **browser** (after the other two): `npm run e2e` in the runner's Chrome, uploading traces on failure.

The 720-run sweep comparison and the 520-run laboratory collection (about four minutes) stay out of CI
on purpose. Run them locally after any change to the reasoner, a policy or the reducer
(see [CONTRIBUTING.md](../CONTRIBUTING.md)).

If `test_pinned_runs.py` or `test_lab_results.py` fails on another platform, treat it as a possible
determinism defect, not as runner noise, and do not refresh the expected hashes to make it pass. The
cross-site browser test skips with an annotation
if the runner's Chrome blocks the request itself; a skip there means that check did not run.

## Known issues

- The first run list after a change to the reasoner or the replay sources replays every stored run once
  (DECISIONS D25). Measured at about 0.08 s for a 243-event run, so a database of a thousand runs takes
  around 80 s the first time. Assessing runs lazily, when each is opened, would remove this.
- The laboratory's recorded results ship with the repository, not with the Python package. An installed
  wheel shows the laboratory page with no recorded results; the bounded re-runs still work. The built web
  interface is not in the wheel either. Running from a clone is the supported way to use CaseForge.
- The interface bundle is about 700 kB and is not code-split. The layout needs a wide window (minimum
  width 1180 px); there is no phone layout.

## What this release candidate promises

Scope: local, single-user, offline, run from a clone. The promise covers the event format of
`ENGINE_VERSION` 3 and its hash chain, the documented CLI and API for local use, and the stored-run
behaviour described in the README, which has two distinct cases. A run recorded by a different engine
version or scenario version is listed but cannot be opened. A run of the current format that the current
rules would not reproduce stays readable, verifiable and branchable from before the divergence, but cannot
be continued. Nothing is rewritten in either case.

The laboratory is an internally pre-registered collection, not an independent benchmark. A packaged wheel
with the interface, multi-user use, authentication and real-model support are out of scope.

## Versioning

The package version is independent of the engine and the rules. `1.0.0rc1` in `backend/pyproject.toml` and
`backend/caseforge/__init__.py`, and `1.0.0-rc.1` in `frontend/package.json` and its lockfile, are the same
version in each ecosystem's notation. `ENGINE_VERSION`, `RULES_VERSION`, the scenario versions and the
laboratory manifest are unchanged. The package version is not part of any event, hash or replay source, so
stored runs and recorded hashes are unaffected. It does appear in `GET /api/health`.

Later: lazy compatibility assessment with an explicit re-verify action in the interface, a wheel that
includes the interface and the recorded collection, challenges written by someone other than the author
of the rules, a smaller bundle, and `httpx2` in the test dependencies.
## Security assumptions

- **Single user, one machine, no authentication.** Anyone, or any program, that can send HTTP to the port
  can read every run, reveal solutions, delete runs and start bounded laboratory executions. The default
  bind address is 127.0.0.1, and `serve` warns if you choose anything else.
- **Host allow-list.** Only `localhost`, `127.0.0.1` and `::1` (any port) are accepted, plus the address
  given to `--host` and any `--allow-host` names. A wildcard bind (`0.0.0.0`, `::`) adds nothing, and
  `--allow-host "*"` is refused. This stops DNS rebinding. A local program can still send any `Host`.
- **Origin check on POST, PUT, PATCH and DELETE.** A page of another site cannot change state, even through
  an allowed loopback name. Clients that send no `Origin` (curl, scripts, the test clients) are not
  affected. Ports are not compared, so another web server on `localhost` is not kept apart from CaseForge.
- **Browser protections are a bonus.** Current Chromium refuses a public page's request to a loopback
  address by itself. The server's checks do not depend on that.
- **The database belongs to the user.** The integrity checks are there to catch accidents and inconsistent
  edits, not an adversary who can write the file (next section).
- **No network access by default.** Tests never touch a network. Model-backed agents are opt-in and run
  against a call budget.

## What the passing tests do not show

- **That the reasoner is right.** Four laboratory predictions were wrong, six reasoning cases are strict
  expected failures, and "wrong but supported" outcomes exist. Support is never treated as truth.
- **That the compatibility gate covers everything.** It replays a recorded log through the engine and the
  reasoner. It deliberately does not judge policies, because a policy that would choose differently today
  does not make the recorded past wrong. A change that only touches policies leaves old runs continuable;
  `tests/test_pinned_runs.py` is what catches policy drift.
- **That a stored log is authentic.** Each run's event log is a SHA-256 hash chain. It detects accidental
  corruption and inconsistent edits (one changed, reordered or missing event). It is not signed or keyed:
  anyone who can write the database can rewrite a log and recompute its hashes, and a truncated log is
  itself a valid chain unless its head is compared with a hash recorded elsewhere. Before a stored run is
  continued, CaseForge replays its recorded decisions through the current build and requires every event to
  be reproduced. That shows the log is what this build would have written from those decisions, not who
  made them. The result is cached in the run's metadata and reused while the build's behaviour fingerprint
  and the event count are unchanged. That metadata (the stamp, the cached verdict, labels, lineage and the
  reveal flag) is trusted local data and is not protected by the chain, so an edited database can carry a
  false stamp or verdict and a matching cache is accepted without a replay. **Verify** recomputes the chain
  and the replay from scratch. The head hashes recorded in the README tables, `tests/test_pinned_runs.py`
  and the laboratory results are the only anchors outside the database, and they cover only those runs.
