# Contributing

Thanks for taking a look. CaseForge is small, but several of its properties (determinism, the separation
between what is true and what an agent knows, the recorded benchmark figures) are easy to break by
accident. This file lists the rules that keep them intact and the checks to run before sending a change.

Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) first, then [docs/DECISIONS.md](docs/DECISIONS.md) for
why things are the way they are.

## Checks

From `backend/`, with the virtual environment active:

```powershell
pytest                                   # must stay green
python -m caseforge validate             # scenario lint
python -m caseforge lab check            # the laboratory's variants lint, and the build is the registered baseline
python -m caseforge demo --seed 7        # a narrated run
```

After any change to a policy or to `reasoning.py`, also run both sweeps and compare them with the tables
in the README:

```powershell
python -m caseforge sweep --seeds 0-39
python -m caseforge sweep --scenario quiet_substitution --seeds 0-39
```

From `frontend/`:

```powershell
npm run build                            # type-check and build
npm run e2e                              # build, then browser tests against the real server
```

## Rules the code depends on

These are enforced by tests where possible. A change that needs to break one should say so and explain
why in `docs/DECISIONS.md`.

- **Policies see an `AgentView` and nothing else.** Modules under `policies/` may import only `models`,
  `canon`, `reasoning` and each other. A test parses the imports.
- **The truth of a scenario is read in three places only:** the lint in `scenario.py`, `evaluation.py`, and
  the graph overlay in `service.py` that appears after a run is revealed. A test checks this.
- **Agendas and an agent's own observations are private.** `private.agendas` reaches its owner through
  `views.py`, and the observer only for an unlocked run. `private.observations` is read by `views.py` and
  the lint. Tests list the modules allowed to touch each.
- **State changes only through `apply_event`.** Never mutate `SimState` elsewhere, and never recompute
  beliefs in the reducer.
- **Nothing nondeterministic reaches an event.** No floats, wall-clock values, random ids, or unsorted set
  or dict iteration. Randomness comes from `DeterministicRng`.
- **The store receives whole operations or nothing** (`RunService._commit`). Events and the compatibility
  coverage that describes them are written in one transaction. Fault tests inject failures in SQLite with
  a trigger rather than by patching the method under test.
- **The API answers only to loopback Host names**, plus any named with `--allow-host`, and refuses a
  state-changing request from a foreign `Origin` (`netguard.py`). This is not authentication. Test clients
  use `LocalClient`, never Starlette's `testserver` host.
- **No hidden truth in the API responses of an open run.** New read routes must be added to the canary list
  in `tests/test_api.py`; new laboratory read routes go in `LAB_READ_ROUTES` in the same file.
- **A requester never sees what was withheld from it.** `RequestState.withheld` must not enter
  `RequestView`.
- **Evidence asserts facts, never guilt.** Do not add fields that say whom a record implicates.
- **A statement is not a fact, and the engine never checks one.** `Tell` is validated for form and for the
  speaker knowing the entities it names. Nothing in `actions.py`, `policies/` or `reasoning.py` may look up
  whether a statement is true; only `evaluation.py` does.
- **A listener is told what was said and by whom, not what the speaker had for it.**
  `StatementMade.grounds` and `backing` must not enter the recipient's `StatementView` or a
  recipient-perspective graph node.
- **Credibility comes from the listener's own hard evidence.** Never from the truth, never from other
  speakers agreeing, and never as a global score.

## Conventions

- **Versions.** Changing reducer behaviour for an existing event type means bumping `ENGINE_VERSION` and
  adding a row to the table in `docs/EVENT_MODEL.md`. Old runs then stop loading, by design. A change that
  alters what revision emits for existing runs is a behaviour change even if the reducer is untouched, and
  also needs a new engine version (DECISIONS D20). Changing a weight or a rule in `reasoning.py` means a new
  `RULES_VERSION`.
- **Pinned runs.** `tests/test_pinned_runs.py` fails when runs change. Re-measure both sweep tables in the
  README first, then update the pins.
- **Hand-worked expectations.** Expected values in reasoning and evaluation tests are literals worked out by
  hand, with the real culprit stated beside them. Do not compute them with the reasoner.
- **Rules are general.** A rule added for one scenario must not mention scenario ids or flags in
  `reasoning.py` or `policies/`. The other scenario's pinned runs show whether it changed anything there.
- **Recorded limits are not targets.** `tests/test_challenge.py` records results against a rule set. Do not
  tune rules to make a recorded limit pass. If one starts passing, the strict expected failure fails: move
  the case, update the recorded results and say so in `docs/DECISIONS.md`.
- **The counterfactual collection is registered.** `caseforge/challenges/` and `docs/LAB.md` are registered
  against a rule set, an engine version, scenario hashes and a fingerprint of `reasoning.py` and the
  deterministic policies. Changing any of those makes `lab run` refuse and `tests/test_lab.py` fail. Then
  re-register the manifest, re-run the collection
  (`python -m caseforge lab run --seeds 0-39 --replay every`, about four minutes), replace
  `docs/lab/collection-1/` and the figures in `tests/test_lab_results.py`, and say what moved. Never edit a
  recorded figure or the fingerprint by itself. A new or changed challenge is committed with its
  expectations and predictions before it is run.
- **The laboratory stays outside the agents.** `lab.py` edits scenario data and reads outcomes from
  `evaluation`. It must not read `.truth`, `.agendas` or `.observations`, and must not pass anything to a
  policy. A variant that the lint rejects is not run. `lab_service.py` releases ground truth only with
  `reveal`; executing from the web interface is bounded to ten seeds, uses registered policies only, is
  refused if the build has drifted from the registered baseline, and never stores a run. Opening a page
  runs nothing.
- **Manifest versions.** A manifest version this build does not read is refused before anything runs
  (`lab.SUPPORTED_MANIFEST_VERSIONS`). Adding a version means writing its reader.
- **Playable challenges and reasoning-only fixtures are never reported in one table.**
- **Stored runs.** A stored run continues only if replaying its recorded decisions through the current
  build reproduces every event (`compat.py`, DECISIONS D25). The stamp and the verdict live in the `runs`
  table, never in `RunStarted` or any hashed field. Editing a file in `compat.REPLAY_SOURCES` makes every
  stored run be replayed once. A change that makes recorded runs diverge turns them read-only (still
  listed, readable and verifiable). Do not weaken this gate to make a test pass, and never delete or
  rewrite a stored run to resolve it.
- **Metrics are counts with denominators.** A zero denominator gives `pct: null`.
- **Model calls stay opt-in** through environment variables. Tests never touch a network.

## Reporting problems

Please open an issue with the command you ran, what you expected and what happened. For anything that
looks like a determinism problem (a different head hash for the same seed and condition), include the
platform, the Python version and the output of `python -m caseforge demo --seed 7`.
