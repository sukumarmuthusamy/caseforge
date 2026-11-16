# Counterfactual laboratory

A way to ask "what would the same team do if the case were different?" and
get an answer that can be run again.

> The challenges in this collection were written by the author of the rules,
> with the rules in view. They are **internally pre-registered challenges, not
> an independent benchmark.** They show where the rules fail on cases their
> author could think of. They say nothing about cases the author could not think of.

Code: `backend/caseforge/lab.py`. Collection:
`backend/caseforge/challenges/counterfactual.json`. Recorded results:
`docs/lab/collection-1/results.json` and `report.md` (generated).

## What a challenge is

A **variant** is a bundled scenario with a list of edits applied: add, change
or remove a record; change who can be asked about what; add a person; change
the truth block. Every edit states why it is made. A **challenge** runs a
variant under a stated policy assignment over a range of seeds. Each one
states beforehand:

- who did it;
- its *expectations*, each of one kind:
  - `contract`: must hold whatever the rules are (the run replays; no
    deterministic policy proposes an illegal action; one voice never weighs
    more than one voice). A failure is a software defect.
  - `design`: the condition the challenge exists to create (a lie was told;
    the stated culprit is the scenario's). A failure means the run does not
    test what it claims to.
  - `ideal`: what a careful investigator would do. A failure is a limit of
    the policy or the reasoner. It is reported, and nothing is tuned.
- the author's *prediction* for each expectation (`holds`, `fails`, `mixed`),
  so the report can show where the author was wrong about those rules.

A run's verdict follows from which kind failed: `contract_violation`,
`invalid_instance`, `falls_short`, or `meets_ideal`. Outcome categories are
the evaluation's own: correct or wrong, supported or not, and unresolved.

## Two kinds, never in one table

| | Playable | Reasoning-only |
|---|---|---|
| What it is | A variant scenario | A list of items handed to `reasoning.revise` |
| Validation | The ordinary Pydantic models and the ordinary lint. A variant the lint rejects cannot be run. | Structure only |
| Execution | The ordinary engine, policies, permissions and action checks, over seeds | One call to the reasoner |
| What it shows | What the team does | What the rules conclude from given information |
| What it cannot show | Anything the lint forbids: a false record, an unsolvable case | Acquisition, order of discovery, who talks to whom |

Some questions can only be asked one way. Two instruments that contradict
each other cannot be played, because records in a scenario must be true; a
case whose only witness is discredited cannot be played, because the lint
finds it unsolvable. Those are reasoning-only fixtures and are reported apart.

## What a transformation may not do

`apply_ops` refuses an edit that names something absent, uses an unknown
field, changes nothing, or gives no reason. The result must then load through
the scenario models and pass `lint`, which is what stops the shortcuts:

- changing only `truth.culprit`: rejected (`truth.facts must state that the
  culprit took the object`, and the records still point at the old one);
- swapping culprit and time in the truth block without rewriting the logger
  and the laboratory comparison: rejected (a record asserts something false);
- removing a record the case rests on: rejected as unsolvable.

So the role permutation in this collection (`curator_did_it`) is a narrow,
hand-written one: two truth facts, the culprit, the account, the key records
and facts, and the two instruments that date the exchange, rewritten to agree.
It is not a generator. Nothing here permutes roles automatically.

A variant has its own scenario id (`quiet_substitution.<variant>`) and version
(`1.1.0+<variant>.<revision>`), so its runs can never be taken for runs of the
case it came from.

## The frozen baseline

The manifest records what it was registered against, and the runner compares
that with the running build before it reports anything:

| | Registered |
|---|---|
| Engine version | 3 |
| Rule set | `2026.11-voices` |
| Behaviour fingerprint | `176b7461d5339758` (SHA-256 over `reasoning.py` and `policies/{__init__,base,baseline,deceptive}.py`, line endings normalised) |
| Base scenario | `quiet_substitution` 1.1.0, hash `3f203e24f527` |

If any of these differ, `lab run` refuses with the differences listed.
`--allow-drift` runs anyway and writes the drift into the results.
`--policy agent=name` is allowed and marks the results as not the registered
configuration. All four can be checked against the published files with
`python -m caseforge lab check`.

Protocol followed for collection 1:

1. Rules and policies frozen (rule set `2026.11-voices`, after the
   one-voice-per-zone correction, DECISIONS D23).
2. Runner built and exercised with the `control` challenge only.
3. Every variant built and linted. The lint uses the reasoner to decide
   solvability, so the author knew each variant was solvable in principle.
4. Expectations and predictions committed before any other challenge was
   run. One exception, disclosed: the test suite at that point ran the
   reasoning fixture `two_keyholders` to exercise the runner; its outcome was
   asserted nowhere and not looked at.
5. One run of everything, seeds 0 to 39, every run replay-verified, on
   2026-11-15. Results committed as they came out. No rule, policy or
   challenge was changed afterwards.

Steps 1 to 5 happened in the project's development history, which is not
published. This repository starts from a single snapshot, so the order of
registration and running is stated here but cannot be checked from its
history.

**Revision for publication (2026-11-16).** The manifest was revised in wording
only: the question of `one_voice_two_doors` cited an internal review
identifier and now describes the same pattern in words, `frozen` no longer
names a commit of the unpublished history, and the protocol says where the
order of registration was recorded. No variant, edit, expectation,
prediction, policy, rule or seed changed. The whole collection was then run
again (`lab run --seeds 0-39 --replay every`) under the same frozen
baseline and compared with the first run value by value: of 23,759 recorded
values in `results.json`, the only differences are the revised question
text and the removed commit field. Every run row, head hash, outcome count,
verdict and prediction outcome is identical, all 520 runs pass replay
verification again, and `report.md` differs only in that question.

The six limits in `tests/test_challenge.py` are untouched and still expected
failures.

## Commands

```powershell
python -m caseforge lab list                       # challenges, kinds, categories
python -m caseforge lab show lie_survives          # edits, culprit, expectations, predictions
python -m caseforge lab check                      # build and lint every variant; compare build with baseline
python -m caseforge lab run                        # everything, seeds 0-39, one replay check per challenge
python -m caseforge lab run playable --seeds 0-39 --replay every --out ..\docs\lab\collection-1
python -m caseforge lab run surviving_lie custodian_hasty --seeds 0-9 --json
python -m caseforge lab reproduce lie_survives --seed 0 --timeline   # one run again, narrated, replay-checked
python -m caseforge lab reproduce instrument_outvoted                # a reasoning fixture, with every weight
python -m caseforge lab export curator_did_it --out curator.json     # then: demo --scenario curator.json
```

`run` exits 1 only if a contract is violated. Falling short of an ideal is a
finding, not an error. `--out` writes `results.json` (every run row, every
aggregate) and `report.md`. The terminal summary lists each challenge with
runs that do not meet the ideal and the command that reproduces one.

A variant exported with `lab export` is an ordinary scenario file: `validate`,
`demo` and `sweep` take it with `--scenario`. The web interface lists bundled
scenarios only, so a variant cannot yet be opened there.

## Collection 1: results

Seeds 0 to 39, 13 playable challenges (520 runs) and 5 reasoning fixtures.
All 520 runs replayed to the same head hash at all four levels. No contract
violation, no invalid instance.

### Playable

| Challenge | Category | Policies | Culprit | Correct, supported | Wrong, supported | Unresolved | Median ticks when solved | Meets ideal |
|---|---|---|---|---|---|---|---|---|
| `control` | control | baseline | Marsh | 40 | 0 | 0 | 19 | 40/40 |
| `custodian` | innocent custodian | baseline | Marsh | 40 | 0 | 0 | 18 | 40/40 |
| `custodian_hasty` | innocent custodian | hale=hasty | Marsh | 16 | 24 | 0 | 19 | 16/40 |
| `mistaken_witness` | mistaken testimony | baseline | Marsh | 40 | 0 | 0 | 24 | 40/40 |
| `lie_survives` | surviving lie | ibarra=deceptive | Marsh | 0 | 0 | 40 | - | 0/40 |
| `second_routes` | route variation | baseline | Marsh | 40 | 0 | 0 | 24 | 40/40 |
| `sealed_motive` | route variation | baseline | Marsh | 0 | 0 | 40 | - | 0/40 |
| `sealed_motive_deceptive` | route variation | ibarra=deceptive | Marsh | 26 | 0 | 14 | 20 | 26/40 |
| `more_witnesses` | provenance conflict | baseline | Marsh | 40 | 0 | 0 | 21 | 40/40 |
| `more_witnesses_hasty` | provenance conflict | hale=hasty | Marsh | 0 | 40 | 0 | - | 0/40 |
| `curator_did_it` | role permutation | baseline | Fenwick | 40 | 0 | 0 | 17 | 40/40 |
| `curator_did_it_hasty` | role permutation | hale=hasty | Fenwick | 40 | 0 | 0 | 13 | 40/40 |
| `curator_did_it_deceptive` | role permutation | ibarra=deceptive | Fenwick | 40 | 0 | 0 | 18 | 40/40 |

No run was correct-but-unsupported or wrong-and-unsupported. Evidence
coverage, statement counts, credibility revisions and contradiction handling
per challenge are in `docs/lab/collection-1/report.md`.

### Reasoning-only

| Fixture | Category | Culprit | Standard met for | Verdict |
|---|---|---|---|---|
| `two_records_disagree` | provenance conflict | Bob | nobody | meets ideal |
| `instrument_outvoted` | provenance conflict | Bob | **Ann** | falls short |
| `one_voice_two_doors` | surviving lie | Bob | nobody | meets ideal |
| `admission_against_interest` | mistaken testimony | Bob | nobody | falls short |
| `two_keyholders` | innocent custodian | Bob | Bob | meets ideal |

### Predictions

65 of 69 playable expectations and all 16 reasoning expectations went as
predicted. The four that did not:

| Challenge | Expectation | Predicted | Observed |
|---|---|---|---|
| `custodian_hasty` | the innocent custodian is not accused | mixed | holds, 40/40 |
| `lie_survives` | no listener still accepts a false statement at the close | mixed | fails, 0/40 |
| `more_witnesses_hasty` | the curator is not accused | mixed | fails, 0/40 |
| `more_witnesses_hasty` | the culprit is accused with support | mixed | fails, 0/40 |

## What the results show

**1. A lie nobody can check stops the investigation, and the liar is never
doubted.** (`lie_survives`, 0 of 40 solved.) The registrar tells three
colleagues the conservator was at the reception; two pass it on. With no
record placing the conservator anywhere on Thursday, 200 of 200 false
statements were accepted at some point and none was ever rejected. The
inspector ends up *questioning* it (120 of 120) once the steward's sighting
arrives; security and the examiner still accept it at the close (80 of 80).
The conservator's opportunity stays contested, so nobody is accused. In
every run the inspector impeaches the steward (honest, wrong about the
dealer), the night guard (honest, mistaken about Friday) and the conservator
(the culprit, whose Friday claim is false), and never the registrar, whose lie
is the one that cannot be checked.
The registrar also withheld the Thursday key-register page 79 times and was
never caught (0 of 79; in the bundled case 28 of 48). Withholding is noticed
only when the withheld record itself arrives by another route, and here it
has none: the key cabinet log says the same thing but is a different record.
So in this variant obstruction is free, the takeover never happens, and
credibility, which comes only from hard evidence, has nothing to work with.
The contract held throughout: repeated and relayed, the alibi never weighed
more than one voice (support at most 2 in the inspector's beliefs).

**2. Haste is right or wrong by the shape of the case, not by anything it
checks.** The same hasty inspector accuses the curator in 24 of 40 runs when
he is innocent (`custodian_hasty`), in 40 of 40 when two more people remember
Friday (`more_witnesses_hasty`), and in 40 of 40 when he is guilty
(`curator_did_it_hasty`), in every case with the standard of proof met on
what she held. The last table looks perfect and is the same behaviour.
"Correct and supported" does not distinguish care from luck; only running the
same policy on the permuted case does. The author predicted a mix in
`more_witnesses_hasty`; it was total: with Friday at 7 from recollection, no
order of discovery lets the logger alone (4) reverse it before the curator's
Friday is complete.

**3. The innocent custodian was safe, for a reason the author did not
predict.** With a key, a motive and a sighting against her, the registrar was
never accused, even by the hasty inspector (prediction: sometimes). The
hasty runs went wrong toward the curator at ticks 8 to 13, before the
registrar's three legs were ever assembled. This is not evidence that lawful
custody is handled well: the recorded limit "lawful access and an ordinary
motive" in `test_challenge.py` still stands. It shows that in this building
the curator is the nearer mistake.

**4. Head-counting can overturn an instrument.** (`instrument_outvoted`,
reasoning only.) Four honest recollections (8) outweigh one forensic finding
(5); the time moves, and an innocent keyholder who was there at the
remembered time is convicted with all three legs. In the playable
counterpart (`more_witnesses`) the careful inspector is protected only
because two instruments exist and she waits for both (10 against 7, with the curator's own
word).

**5. An admission is discounted like a denial.**
(`admission_against_interest`.) A suspect's word about his own whereabouts
weighs 1 whichever way it cuts, so a culprit who admits he was there, with
key and motive on record, is not convicted.

**6. The case can depend on someone misbehaving.** With the motive only in
the confidential file, an honest team never solves it (0 of 40) and wrongly
accuses nobody. A registrar who withholds gets caught in 26 runs, the
inspector takes over her sources, reads the file, and solves the case in
exactly those 26. Obstruction opened the only route.

**7. What held.** Losing the most direct record on each leg costs time
(median 24 against 19) and no accuracy. An honest witness who is wrong about
one person and right about another is impeached in every run, and the case
is still made, with no margin: her discounted word (1) plus the
conservator's own statement (1) is exactly the threshold. The role
permutation is solved 40 of 40 with the conservator never accused, and a
registrar lying to protect an innocent person is caught in all 40.

## Reproducing

Every row in `results.json` carries its seed and head hash. Two examples,
both pinned in `tests/test_lab_results.py`:

```powershell
python -m caseforge lab reproduce control --seed 7        # correct_supported, Marsh, tick 20, head 238fc656b44d...
python -m caseforge lab reproduce lie_survives --seed 0   # unresolved, falls_short, head a9ce531fe6cb...
```

`lab run --seeds 0-39 --replay every --out <dir>` regenerates `results.json`
byte for byte on the registered build; `test_lab_results.py` checks seven
runs, every stored aggregate against its stored rows, and the report against
the results.

## Limits of this laboratory

- Same author, same rules in view. See the top of this page.
- One base scenario. `missing_prototype` has no variants yet.
- Predictions were mostly right (81 of 85), which is what one expects from an
  author predicting the behaviour of rules they wrote, and is itself a sign that these challenges
  mostly document what the author could already see.
- The ideals are the author's judgment of what a careful investigator would
  do. `instrument_outvoted` and `admission_against_interest` are arguable.
- Deterministic policies only. No model-backed agent was run.
- The lint's solvability rule excludes whole classes of playable case (see
  the table above). Those can only be reasoning fixtures.
- No automatic generation. Each variant is hand-written and small.
- 40 seeds per challenge. Counts are reported as counts; no interval is
  claimed.
- The web page (below) shows and re-runs this collection; it adds no results of its own.

## In the web interface

The **Counterfactual Lab** view (`#lab`, or the button in the top bar) is a reader and a small, bounded runner over the
collection above. DECISIONS D26 has the reasoning.

| Route | What it does |
|---|---|
| `GET /api/lab` | The overview: registration, drift, the recorded aggregates, prediction counts (playable and reasoning-only separate), the wrong predictions, the recorded limitations. Runs nothing. |
| `GET /api/lab/challenges/{id}` | One challenge: configuration, the recorded aggregate and every recorded seed. `?reveal=true` adds who it was written around, the edits, the question and prediction prose, who was accused and which voices the accuser distrusted. |
| `POST /api/lab/challenges/{id}/execute` | `{"seeds": [...], "replay": bool}`. At most 10 seeds, the registered policies only, local, deterministic, one at a time, refused when the build is not the registered one, nothing stored. Each seed is compared with the record by head hash. A reasoning fixture runs once. |
| `POST /api/lab/challenges/{id}/open` | `{"seed": n}`. Starts an ordinary run of the challenge's variant (`<base>.<variant>`) with its registered policies. It reproduces the recorded head hash for that seed. Reasoning-only fixtures refuse. |

Figures are labelled by where they come from: *stored* (read from `docs/lab/collection-1/results.json`; override with
`CASEFORGE_LAB_RESULTS`), *executed just now*, and the same with *all four replay levels checked*. If the recorded file
is missing (an installed wheel has no `docs/`), is of another manifest version, or was recorded against another
registration, the page says so and shows no figures; re-running is still offered when the build is the registered one.

What the page does not do: compare collections, run custom challenges, show a per-event trace of a recorded run (open
it as a run for that), or say the reasoner is right. The label that these are internally pre-registered challenges, not
an independent benchmark, is shown at the top.
