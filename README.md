# CaseForge

CaseForge is a simulation in which a small team of software agents investigates a fictional crime. Each
agent has its own access, its own goals and its own idea of what counts as enough evidence. They search
records, ask each other questions, form and drop suspicions, and eventually someone may accuse a suspect.
The simulation knows who really did it; the agents never see that. When the case closes, their work is
scored against the truth.

The project is about a question that is easy to blur: when an investigator reaches a conclusion, was it
right, and was it justified by what they actually held? Those are different things, and CaseForge keeps
them apart. An agent can make a well-supported accusation against an innocent person, or a lucky guess
against the guilty one, and the evaluation reports each for what it is.

Everything runs locally. There is no API key, account, database server or Docker to set up.

## What you can do with it

- Watch an investigation tick by tick in a web interface, or run it from the command line.
- Step backwards to any earlier tick and see the case as it stood then.
- Branch a run from any tick, apply an intervention (a leak to the press, a rumor, fast-tracked
  forensics), and compare the two outcomes.
- Swap an agent's policy: a careful baseline, a `hasty` investigator who accuses early, or a `deceptive`
  one with a private agenda.
- Run a seed range and get outcome counts, or run the counterfactual laboratory, a set of
  pre-registered variations of one case designed to probe where the reasoning fails.
- Verify that any stored run replays to the same events, hash for hash.

Two cases are bundled. In *The Missing Prototype* a detective, a researcher, a technician and a journalist
investigate a theft from a research lab, where a door record points at the wrong person. In *The Quiet
Substitution* an inspector, a registrar, a head of security and an examiner work out on which of two
evenings a manuscript was exchanged for a copy, when an honest witness and the culprit both name the wrong
one.

## How an investigation works

**Agents only know what they have obtained.** Each agent sees an `AgentView` built from the records it
holds, what it has been told and what it saw itself. The scenario's truth is never part of a policy's
input, and tests check this by parsing imports and by probing every API route of an open run.

**Evidence states facts, not conclusions.** A record asserts something like "this card was used at this
door at this time". Nothing in a scenario says whom a record incriminates. Suspicion is derived by general
rules about access, custody of a tool, alibis, timing and motive, so the same rules work on both cases.

**Beliefs change for recorded reasons.** Every revision is an event that names the evidence that caused it,
so when the detective drops her first suspect, the log says which record made her do it.

**Agents talk, and may lie.** An agent can tell another what it saw or pass on what it was told. A
statement is not a fact, and the engine never checks whether it is true. The listener believes it until
evidence it holds itself says otherwise, and from then on takes nothing else from that speaker on their
word alone. Credibility is per listener: two agents can judge the same speaker differently. A `deceptive`
registrar can give the person she protects a false alibi; a `deceptive` technician can quietly leave records
out of his answers. Whether the deception was noticed, and what it cost, is measured.

**Runs are deterministic.** The event log is the state: every run is an append-only log of events that is
folded into the current state, and each log is a SHA-256 hash chain. The same scenario, seed and policies
give the same head hash across processes and across `PYTHONHASHSEED` values.

**Evaluation is counts, not a score.** Evidence found, false public claims made and retracted,
contradictions resolved, and whether an accusation met the standard of proof. Each outcome falls into one
of five categories, so being right and being justified are never added together: `correct_supported`,
`correct_unsupported` (a lucky guess), `wrong_supported` (the rules were satisfied by misleading evidence),
`wrong_unsupported` and `unresolved`.

## Requirements

- Python 3.11 or newer. Tested with 3.11 and 3.13 in CI, and with 3.12 locally.
- Node.js 22 or newer, to build the web interface. Tested with 22 in CI, and with 22 and 24 locally.
- A Chromium-based browser for the browser tests (Edge or Chrome). Not needed to use CaseForge.

Development was done on Windows 11, where the tests were also run locally. GitHub Actions runs the backend
tests, the frontend build and the browser tests on Ubuntu. macOS has not been tested. See
[docs/RELEASE.md](docs/RELEASE.md) for exactly what has been verified.

## Installation

```powershell
git clone https://github.com/sukumarmuthusamy/caseforge.git
cd caseforge

# Backend
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Web interface: built once, then served by the Python server
cd ..\frontend
npm install
npm run build

# Start
cd ..\backend
python -m caseforge serve
```

Open <http://127.0.0.1:8000> and choose **Open the case**.

On Linux or macOS the steps are the same except for activating the environment
(`source .venv/bin/activate`) and the path separators. If PowerShell refuses to run the activation script,
run `Set-ExecutionPolicy -Scope Process RemoteSigned` in that window first.

Runs are stored in `caseforge.sqlite3` in the directory you start the server from; `--db PATH` chooses
another file.

## A first investigation

The interface has a top bar for choosing a run and stepping it (**Step** advances one tick in which every
agent acts once, **Play** steps continuously, **Run to end** finishes the case), a tick slider for moving
back in time, the agents on the left, a knowledge graph of who holds which record, and the event log as a
timeline. Selecting an agent shows its suspects, its beliefs with the evidence for and against each, the
records it holds with their chain of custody, and a decision trace of what it chose, why, and what else it
considered. The evaluation stays locked while a case is open so that watching cannot spoil it.

Some things to try:

1. Run seed 7 to the end. Find the tick at which the detective drops her first suspect and the record that
   caused it.
2. Drag the slider to tick 6, open the **Lab** tab, branch, apply *Leak the door log to the press*, and run
   the branch to the end. Compare it with the original.
3. Start a new run with the detective's policy set to `hasty` and seed 4.
4. Start a new run with Jonah Reyes, the technician, set to `deceptive` and seed 7. The purple timeline
   entries are his. His **Requests** tab shows what he held back. Compare the finishing tick with the honest
   run from step 1.
5. Choose **New run**, pick *The Quiet Substitution*, set the inspector to `hasty` and the seed to 3. She
   accuses the curator on evidence that meets the standard of proof, and he is innocent. Run the same seed
   with the `baseline` policy and read her decision trace around the point where she asks for the case
   logger.
6. In *The Quiet Substitution*, set Lucia Ibarra, the registrar, to `deceptive`, use seed 7 and step to
   tick 8. Open the inspector's **Said** tab: the registrar's statement that the conservator was in the
   Great Hall is marked *accepted* at tick 1 and *rejected* at tick 2. Drag the slider back to tick 1 and it
   is accepted again. Switch the graph to *Seen by* the inspector and the note that the registrar had
   nothing to back the statement disappears, because the inspector was never told that.

The same runs from the command line:

```powershell
python -m caseforge demo --seed 7                       # narrated run, then evaluation and replay checks
python -m caseforge demo --seed 4 --policy okafor=hasty --quiet
python -m caseforge demo --seed 7 --policy reyes=deceptive
python -m caseforge demo --intervene leak_door_log@0
python -m caseforge demo --scenario quiet_substitution --seed 7 --policy ibarra=deceptive
python -m caseforge validate                            # lint the bundled scenarios
```

`validate` also reports, for every agent who may accuse, whether the case is solvable by a cooperative
team or only after that agent takes over another agent's sources, and how many records fall in each class.

### Runs recorded under other rules

A stored run's beliefs were computed by whichever version of the reasoner was running when it was recorded.
When the rules change, CaseForge decides once per run whether it may still be continued, by replaying the
recorded decisions through the current engine and reasoner and checking that every event comes out the
same. If it does, the run carries on. If it does not, the run becomes read-only: it stays listed, readable
and verifiable, the report names the first event the current rules would not have produced, and you can
branch from a tick before that event. Runs recorded by a different engine version or scenario version are
listed but cannot be opened; they can be deleted. Nothing is rewritten. The reasoning is in
[docs/DECISIONS.md](docs/DECISIONS.md) (D25).

## Measured results

`sweep` runs a range of seeds and tabulates the outcomes:

```powershell
python -m caseforge sweep --seeds 0-39
python -m caseforge sweep --seeds 0-39 --policy reyes=deceptive --intervene grant_systems_access@0
python -m caseforge sweep --scenario quiet_substitution --seeds 0-39 --policy hale=hasty --json
```

*The Missing Prototype*, seeds 0 to 39:

| Condition | Solved | Wrong accusation | Unresolved | Median ticks when solved | Notes |
|---|---|---|---|---|---|
| Baseline | 40 | 0 | 0 | 17 | range 12 to 20; 38 of 40 false public claims retracted |
| Detective `hasty` | 30 | 10 | 0 | 17 | accuses before hearing the accused |
| Door log leaked to the press | 40 | 0 | 0 | 16 | false public claims double from 40 to 80 |
| Rumor about the contractor | 40 | 0 | 0 | 19 | a rumor cannot meet the standard of proof, but it costs two ticks |
| Forensics fast-tracked, direct systems access | 40 | 0 | 0 | 15 | 32 of 40 false claims corrected before the case closes |
| Technician `deceptive` | 25 | 0 | 15 | 23 | range 20 to 39; false public claims 80; 158 answers held records back, 97 were noticed; the detective went over his head in 31 runs |
| Technician `deceptive`, detective `hasty` | 20 | 6 | 14 | 22 | |
| Technician `deceptive`, direct systems access from the start | 29 | 0 | 11 | 20 | four more cases solved than without the access |

Under deception no case is solved unless the detective first catches an omission: a record reaches her by
another route (a second operator, or her own search) that an earlier answer had left out. In the 15
unresolved runs she either never got such a record or got it too late.

*The Quiet Substitution*, seeds 0 to 39 (add `--scenario quiet_substitution`):

| Condition | Solved | Wrong accusation | Median ticks when solved | Notes |
|---|---|---|---|---|
| Baseline | 40 | 0 | 19 | range 16 to 22; 2 statements per run, both true |
| Inspector `hasty` | 20 | 20 | 20 | all 20 name the curator, and all 20 meet the standard of proof |
| Conservator volunteers her statement | 40 | 0 | 18 | range 14 to 22 |
| Conservator volunteers, inspector `hasty` | 0 | 40 | - | all 40 supported |
| Logger download fast-tracked | 40 | 0 | 16 | range 10 to 20 |
| Rumor about the registrar | 40 | 0 | 20 | |
| Inspector given the security systems | 40 | 0 | 17 | |
| Registrar `deceptive` | 40 | 0 | 21 | range 16 to 28; 200 false statements, 117 accepted by their listener at some point, 0 still accepted at the close; 48 answers held records back, 28 were noticed; the inspector went over her head in 25 runs |
| Registrar `deceptive`, inspector `hasty` | 18 | 22 | 21 | all 22 supported; 200 false statements, 117 accepted at some point, 0 at the close |
| Registrar `deceptive`, conservator volunteers | 40 | 0 | 21 | 200 false statements, 54 accepted at some point, 0 at the close |

No run of this case ends unresolved. These figures are for scenario version 1.1.0, in which two agents have
something they saw and say it; the table for 1.0.0 and what changed is in
[docs/SCENARIO_QUIET_SUBSTITUTION.md](docs/SCENARIO_QUIET_SUBSTITUTION.md). The first case's table did not
change when testimony was added: nobody in it has anything to say, and its 320 runs make the same
decisions as before.

How to read these tables:

- **A supported accusation can be wrong.** "Met the standard of proof" is judged on what the accuser held,
  not on the truth. The sweep summary counts `wrong_but_supported` separately; in both cases here, every
  wrong accusation was supported.
- **A lie that is always caught is a property of this case.** The registrar's false alibi concerns a place
  that two records cover, so every listener ends up holding evidence against it. The counterfactual
  laboratory and `tests/test_challenge.py` include cases where the same rules are fooled.
- **These are authored policies on two authored cases.** The baseline solves both because its rules were
  written with these cases in view, and one rule was added because the second case defeated it (see
  [docs/SCENARIO_QUIET_SUBSTITUTION.md](docs/SCENARIO_QUIET_SUBSTITUTION.md)). The numbers are not evidence
  of general investigative ability.

## Counterfactual laboratory

The laboratory runs controlled variations of *The Quiet Substitution* against a frozen rule set: an
innocent keyholder, a lie that nothing can refute, an honest witness who is wrong, the same facts reached by
other routes, recollection against instruments, and a different culprit with the evidence rewritten to
match. Each challenge states who did it, what a careful investigation should do, and what the author
predicted the reasoner would do. These were written down before the challenges were run, in the
project's development history; that history is not published, so this repository cannot show the order
(see [docs/LAB.md](docs/LAB.md)). Variants must pass the ordinary scenario lint and are played by the
ordinary engine.

```powershell
python -m caseforge lab list
python -m caseforge lab show lie_survives
python -m caseforge lab run --seeds 0-39 --replay every     # the full collection, about four minutes
python -m caseforge lab reproduce lie_survives --seed 0 --timeline
```

These challenges were written and pre-registered by the same person who wrote the rules. They are a
structured way of finding weaknesses, not an independent benchmark.

Collection 1, seeds 0 to 39, every run replay-verified (520 of 520 pass):

| Challenge | Policies | Culprit | Correct, supported | Wrong, supported | Unresolved | Median ticks when solved |
|---|---|---|---|---|---|---|
| `control` (the bundled case) | baseline | Marsh | 40 | 0 | 0 | 19 |
| `custodian` | baseline | Marsh | 40 | 0 | 0 | 18 |
| `custodian_hasty` | hale=hasty | Marsh | 16 | 24 | 0 | 19 |
| `mistaken_witness` | baseline | Marsh | 40 | 0 | 0 | 24 |
| `lie_survives` | ibarra=deceptive | Marsh | 0 | 0 | 40 | - |
| `second_routes` | baseline | Marsh | 40 | 0 | 0 | 24 |
| `sealed_motive` | baseline | Marsh | 0 | 0 | 40 | - |
| `sealed_motive_deceptive` | ibarra=deceptive | Marsh | 26 | 0 | 14 | 20 |
| `more_witnesses` | baseline | Marsh | 40 | 0 | 0 | 21 |
| `more_witnesses_hasty` | hale=hasty | Marsh | 0 | 40 | 0 | - |
| `curator_did_it` | baseline | Fenwick | 40 | 0 | 0 | 17 |
| `curator_did_it_hasty` | hale=hasty | Fenwick | 40 | 0 | 0 | 13 |
| `curator_did_it_deceptive` | ibarra=deceptive | Fenwick | 40 | 0 | 0 | 18 |

Some questions cannot be posed as a playable case. Those are reasoning-only fixtures, reported separately:
3 of 5 reach the ideal. In `instrument_outvoted`, four recollections overturn a forensic finding and an
innocent keyholder is convicted. In `admission_against_interest`, a culprit's own admission is discounted
like a denial.

In short: a lie that no record contradicts leaves the case open in every run, and the liar is never
doubted. The hasty inspector is right or wrong depending on the shape of the case (wrong in 40 of 40 runs
when two more people remember Friday, right in 40 of 40 when the curator is in fact guilty, with the same
behaviour). One case is solvable only when the registrar obstructs and is caught. Four of the 85
predictions were wrong, and no rule was changed in response. Method, protocol, analysis and limits are in
[docs/LAB.md](docs/LAB.md), and the full figures in
[docs/lab/collection-1/report.md](docs/lab/collection-1/report.md).

**Counterfactual Lab** in the web interface's top bar shows the recorded collection read from
`docs/lab/collection-1/results.json`. Opening the page runs nothing. Each challenge keeps its ground truth
(who it was written around, the edits that make it, who was accused, the expectations) behind **Reveal the
ground truth**. From a challenge page you can re-run up to ten seeds locally (registered policies only,
nothing stored, refused if this build differs from the registered one), replay a single recorded seed, or
open a seed as an ordinary run to step through.

## Tests and reproducibility

```powershell
cd backend
pytest
```

The backend suite has 658 tests and 6 expected failures. It covers determinism (including across
`PYTHONHASHSEED` values), replay and branching, isolation of the truth from agent views and from every API
read route, action validation, belief revision, the scenario lint, evaluation, persistence and restart,
the deceptive agent, testimony and credibility, the counterfactual laboratory, the stored-run
compatibility check, and the local API guard.

A test that computes its expected value with the code under test only proves determinism, so several
modules get their expectations from elsewhere:

- `test_reasoning_cases.py`, `test_testimony.py` and `test_tiny_case.py` use small cases whose belief
  statuses, scores, credibility judgments and evaluation figures were worked out by hand from the published
  weights. Each case states who really did it, so "the reasoner followed its rules" and "the conclusion is
  true" are checked separately. In two of these cases the rules convict an innocent person, and the tests
  say so.
- `test_challenge.py` runs thirteen cases against a frozen rule set (`reasoning.RULES_VERSION`). For each,
  the conclusion a careful person would reach was written down before the reasoner was run. Seven reach
  it. The other six are kept as strict expected failures, each with a second test stating what the reasoner
  does instead. The rules were not tuned to pass them.
- `test_lab_results.py` holds the recorded laboratory results, reproduces seven runs to the head hash, and
  checks the five reasoning fixtures against hand-worked values.
- `test_pinned_runs.py` holds head hashes of reference runs of both cases. It proves nothing about
  correctness; it fails when behaviour changes, which is the signal to re-measure the tables above.

Browser tests:

```powershell
cd frontend
npm run e2e
```

This builds the interface, starts the real Python server on port 8791 with a throwaway database and the
model-backed policies off, and drives it with Playwright: 32 tests, about two minutes. They cover stepping,
time travel, branching, interventions, replay verification, run comparison, the agent inspector, both
cases, deception and testimony, the laboratory page, and a page of another site trying to change state
through the loopback address. They also check that neither the solution, a private agenda nor the truth of
a statement reaches the browser before it is revealed. Expected values are read from the API during the
test, not hard-coded.

No browser is downloaded. The tests use Edge on Windows and Chrome elsewhere. Set
`CASEFORGE_E2E_BROWSER` to `msedge`, `chrome` or `chromium` to choose (the last needs
`npx playwright install chromium` once). `CASEFORGE_E2E_PORT` and `CASEFORGE_PYTHON` override the port and
the Python interpreter.

The GitHub Actions workflow runs the backend tests on Python 3.11 and 3.13, the CLI checks, the frontend
type-check and build, and the browser tests in Chrome, all on Ubuntu.

## Optional: model-backed agents

Off by default. Nothing contacts a model unless you assign the `llm` policy to an agent and set these
variables before starting the server:

```powershell
$env:CASEFORGE_LLM_ENABLED   = "1"
$env:CASEFORGE_LLM_BASE_URL  = "http://localhost:11434/v1"   # any OpenAI-compatible endpoint
$env:CASEFORGE_LLM_MODEL     = "your-model-name"
$env:CASEFORGE_LLM_API_KEY   = "..."                         # only if the endpoint needs one
$env:CASEFORGE_LLM_MAX_CALLS = "200"
```

The model chooses one action from a menu the engine builds. Its reply is validated against a strict
schema; anything else falls back to the baseline policy and the failure is recorded. Beliefs are still
revised by the rule-based reasoner: the model chooses actions, not conclusions. Replay reads the recorded
decisions and never calls the model again. Providers may charge for usage, so check before enabling.

`CASEFORGE_LLM_MAX_CALLS` is one budget for the whole server process. Every attempted request counts,
retries included, across all runs and branches. Once it is spent, model-backed agents fall back to the
baseline policy until the server restarts. `GET /api/health` reports `llm_calls_used`. This path is
covered by tests with a fake client and has not been tried against a real provider.

## Architecture

A single Python process: a deterministic engine, a rule-based reasoner, SQLite persistence and a FastAPI
server, with a React and TypeScript interface that talks only to the API. No queues, workers or external
services.

```
backend/caseforge/
  models.py       contracts: scenario, propositions, actions, events, agent view
  scenario.py     loading and lint (truth consistency, reachability, solvability)
  scenarios/      the two bundled cases
  reasoning.py    belief revision and suspect assessment (pure functions)
  state.py        simulation state and the event reducer
  views.py        what an agent may see
  actions.py      action preconditions and effects
  policies/       baseline, hasty, deceptive and the optional LLM policy
  engine.py       tick loop, interventions, branching, verification
  evaluation.py   metrics against the ground truth
  graph.py        knowledge-graph projection
  store.py        SQLite persistence
  compat.py       whether a stored run may be continued by this build
  lab.py          counterfactual laboratory: variants, challenges, runner, reports
  challenges/     the pre-registered collection
  lab_service.py  the laboratory as the web interface reads it
  service.py      coordinates engine and store
  netguard.py     Host and Origin checks for the local API
  api.py          FastAPI routes
frontend/src/     React, TypeScript, Cytoscape
frontend/e2e/     Playwright tests against the real server
docs/             design documents
```

Further reading:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): module boundaries, the knowledge model and its weights,
  replay semantics, and how the truth is kept out of agent views.
- [docs/DECISIONS.md](docs/DECISIONS.md): the design decisions, with the alternatives that were rejected.
- [docs/EVENT_MODEL.md](docs/EVENT_MODEL.md): event types, replay guarantees and versioning.
- [docs/SCENARIO.md](docs/SCENARIO.md) and
  [docs/SCENARIO_QUIET_SUBSTITUTION.md](docs/SCENARIO_QUIET_SUBSTITUTION.md): the two cases, and how to
  write another.
- [docs/LAB.md](docs/LAB.md): the counterfactual laboratory.
- [CHANGELOG.md](CHANGELOG.md): what the release candidate contains.
- [docs/RELEASE.md](docs/RELEASE.md): what has been verified, known issues, and what the release promises.

To work on the interface, run `python -m caseforge serve` in one terminal and `npm run dev` in `frontend/`
in another, then open <http://localhost:5173>.

## Limitations

- Two scenarios, both thefts, both written by the author of the rules. The reasoner knows about card
  access, custody of a tool, alibis, rival times and motive. Another kind of mystery would need new
  predicates and rules. Solving both cases shows the rules fit these cases, nothing more.
- The standard of proof can be met against an innocent person. The evaluation reports that as a wrong
  accusation that was supported. Six known weaknesses are recorded as strict expected failures in
  `tests/test_challenge.py`: the reasoner convicts a lawful custodian who has an ordinary motive; one
  uncorroborated true sighting, or one false sighting, can complete a case against an innocent person; it
  does not doubt a speaker who contradicts himself; two friends' agreement can block a true conviction;
  and it treats an honest mistake like a lie.
- Statements are narrow. An agent can say where someone was and when the crime happened, nothing else,
  and cannot take a statement back. In the first case nobody says anything. Only the second case's
  registrar is in a position to lie.
- Lies are caught only with hard evidence. A listener can only reject a statement it holds evidence
  against. It cannot tell a lie from an honest mistake.
- Deception has limited consequences. Being caught lying costs a speaker credibility, not access. Records
  cannot be forged, and the culprit is not a playable agent. One agent per case has an agenda, and only the
  detective can go over another agent's head.
- Agendas leak through traces. An agenda's text is private until a run is unlocked, but a deceptive
  agent's decision trace names the person it protects, so someone who assigned that policy can infer the
  gist from the timeline.
- The hash chain is not a signature. It detects corruption and inconsistent edits, not a deliberate
  rewrite by someone who can write the database. See [docs/RELEASE.md](docs/RELEASE.md).
- Not production software. Single user, local only, no authentication.

## Local use only

The API has no authentication. Anyone who can reach it can read every run, reveal solutions, delete runs
and start laboratory executions. The server binds to 127.0.0.1 by default and prints a warning if you ask
it to listen anywhere else.

Two checks stop a web page in your own browser from using the API, and neither is authentication. The
server answers only to the Host names `localhost`, `127.0.0.1` and `[::1]` (any port), which defeats DNS
rebinding, and it refuses a state-changing request (POST, PUT, PATCH, DELETE) whose `Origin` belongs to
another site. To serve under another name, bind to that address or add `--allow-host NAME` (repeatable).
Binding to `0.0.0.0` does not make every name acceptable, and `*` is refused. A script or another program
on the same machine can still send any Host header it likes, and another web server on `localhost` is not
kept apart from CaseForge by these checks.

## Contributing

Issues and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) lists the checks to run and the
rules the code depends on (truth isolation, determinism, recorded results that must not be edited by hand).

## License

MIT. See [LICENSE](LICENSE).
