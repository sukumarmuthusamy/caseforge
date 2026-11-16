# Architectural Decisions

Short records. Each states the decision, why, and what was rejected.

## D1. Event log plus pure reducer, not full event sourcing

**Decision.** One append-only, hash-chained event log per run. State is
`fold(apply_event, events)`. No command bus, no separate read-model store, no
snapshot table.

**Why.** We need exactly two things from event sourcing: reproducible state
transitions and history that cannot silently change. A run is a few hundred
events; folding it takes milliseconds, so snapshots would be a cache for a
problem we do not have. Time travel is a fold over a prefix.

**Rejected.** (a) Full ES/CQRS: aggregates, projection stores, versioned
upcasters. Infrastructure with no user-visible benefit at this scale.
(b) Mutable state tables plus an audit log: the audit log is then not the
source of truth, replay is unverifiable, and belief provenance is lost.

**Revisit when** runs exceed roughly 50k events: add snapshot rows keyed by
`(run_id, seq)`; the reducer does not change.

## D2. Knowledge graph is a projection; storage is SQLite

**Decision.** Events live in SQLite as JSON payloads. The graph is computed in
Python from state on request and returned as JSON.

**Why.** The graph is ~100 nodes. Required queries are "graph at tick N",
"what does agent X know", and neighbours of a node. A second source of truth
would create a consistency problem that a projection cannot have.

**Rejected.** Neo4j or any graph server (installation burden, violates the
no-external-database requirement). `networkx` (a dependency for what is two
list comprehensions). SQLite node/edge tables (duplicates the log; must be
kept in sync under branching).

**Migration path.** `project_graph` already emits typed nodes and edges with
provenance; exporting to a graph store is a writer, not a redesign.

## D3. React + TypeScript + Vite + Cytoscape; no Tailwind

**Decision.** Keep the proposed frontend stack minus Tailwind. Plain CSS with
custom properties. State lives in React hooks; no state library.

**Why.** Cytoscape is the right tool for an inspectable typed graph with
selection. React is justified by the amount of cross-panel state (selected
agent, selected node, tick scrubber, perspective). Tailwind would add a build
plugin and a second vocabulary for one stylesheet.

**Rejected.** Server-rendered HTML with htmx: fewer moving parts, but the
scrubber/graph/inspector interplay becomes awkward and the graph still needs a
JS island. D3 force layout by hand: more code than Cytoscape for less.

## D4. Agents are policies behind one function, not actors

**Decision.** `Policy.decide(view, rng) -> Decision`. The engine owns the loop,
builds the view, validates the action and applies effects. Agents act
sequentially in a seeded order within each tick.

**Why.** Sequential turns make event order trivially deterministic. An actor
model or async message passing would add scheduling nondeterminism that we
would then have to remove again. Roles differ by data (access, disposition,
initiative), not by class hierarchy.

**Rejected.** Actor model; per-agent state machines (the interesting state is
knowledge, not mode); adopting an agent framework (dependencies, and it would
own the loop we need to control).

## D5. Two replay guarantees, stated separately

Replay-by-fold always holds. Re-simulation equality holds only for
deterministic policies. LLM decisions are stored (request digest, model,
validated action, attempts) and replay reads them back; it never calls a
model. See ARCHITECTURE section 5.

## D6. Metrics are counts with denominators; no composite score

**Decision.** Evaluation reports outcome, evidence coverage, standard-of-proof
check, public-claim accuracy, retractions, contradictions recognized and
resolved, per-agent belief accuracy, and effort. Each as `numerator /
denominator`, with `null` when the denominator is zero.

**Why.** A blended score hides which behaviour changed and invites weight
tuning. Counting only *decided* beliefs (believed or rejected) against truth
means an agent is not rewarded for asserting more.

**"Supported" is defined operationally.** An accusation or public claim of
guilt is supported iff the *reference reasoner* (neutral disposition) applied
to the evidence the speaker held at that moment ranks the named person first
with the accusation threshold and margin. Agreement between agents plays no
part.

## D7. Structured propositions and generic rules, not authored implications

Evidence states what a log or a witness says. It never states whom it
incriminates. Suspicion is derived by four scenario-independent rules. This is
what separates a reasoning environment from a branching script. Cost: authoring
a scenario requires thinking in propositions. Benefit: the lint can prove the
scenario solvable, and a second scenario reuses the reasoner unchanged.

## D8. Counter-based randomness

`sha256(seed | tick | agent | purpose)` instead of a stateful PRNG. No RNG
state in checkpoints, no dependence on `random` internals across Python
versions, and a branch replays its parent exactly until something differs.

## D9. Topic-keyed inspection

`inspect(source, topic)` instead of `inspect(source)`. Agents must decide what
to look for, and leads come from entities mentioned in evidence they hold.
Without this every run collects everything and the metrics are constants.
A query that found nothing may be retried only after the agent acquires new
evidence mentioning that topic, which also handles prerequisite-gated records
without revealing that they exist.

## D10. The culprit is not a playable agent

Two agents are suspects and are innocent; the culprit is a non-agent
character. This still holds after D14: the deceptive agent is an accomplice
after the fact, not the thief. A guilty agent would also need to lie about
his own whereabouts, which needs false statements and a trust model for
testimony (see D14, "not built").

## D11. LLM policies choose actions; belief bookkeeping stays deterministic

The belief table is computed by the rule-based reasoner for every agent. An LLM
policy sees it and chooses among engine-enumerated legal actions. This keeps
beliefs scorable and keeps a malformed model response from corrupting state.
Letting a model own belief revision is a later experiment behind the same
interface.

## D12. Cut from v1

- A separate `verify(claim)` action. Corroboration and refutation already
  emerge from belief revision; a distinct action would be decorative.
- Evidence forgery and record tampering.
- LLM-as-judge evaluation.
- Snapshot storage, auth, multi-user, Docker.

## D13. stdlib `sqlite3` and `urllib`, no ORM, no HTTP client dependency

Two tables do not need an ORM. The optional LLM client posts one JSON body;
`urllib.request` is enough and keeps runtime dependencies at three packages.

## D14. Deception is withholding by a gatekeeper, detected against the log

**Chosen.** One investigator (the technician) can be given the `deceptive`
policy. He follows a scenario-private agenda: answers go out with records
about one person left out, nothing about that person is volunteered, and
records against someone else are leaked to the journalist. The detective
notices an omission when the record reaches her another way, and may then take
direct access to his sources.

**Why this form.** The technician is the only route to most internal records,
so omission by him is the smallest change that can decide a case. It needs no
new kind of evidence and no change to the reasoner: the same rules simply see
less. The effect is large and not degenerate (40 of 40 solved becomes 25 of
40), and the counter-move comes from things the scenario already had: a
second operator for one source, and a detective with authority.

**Alternatives rejected.**
- *The culprit as a fifth agent.* He controls no source, so he could only
  mislead by speaking. That needs a statement action, speaker credibility and
  a way to score lies: three new mechanisms before any measurable effect.
- *The agenda as a policy parameter* (`cover:whitlock`). No private data and
  no spoiler question, but then nothing in the world is known to one agent
  only, which is the property worth testing.
- *Two-phase answers* (search, then decide what to hand over). More faithful,
  but it costs every honest answer an extra tick. A filter stated up front
  (`withhold_about`) gives the same result in one action.
- *Detection from the agent's view alone.* It cannot tell "withheld" from
  "not retrievable yet" for records with prerequisites, so an honest operator
  could be accused. The engine compares against the logged search instead.

**Consequences.** Baseline policies changed for honest runs too: they choose
among a source's operators, ask a second operator after an empty answer, and
escalate on grounds. The honest sweep is unchanged at 40 of 40 with a median
of 17 ticks; the hasty detective's numbers moved (see README).

**Not built.** False statements, forged records, a credibility weight per
speaker, agendas for other agents, and any way for a non-detective to act on
a discrepancy it notices.

## D15. One model-call budget per process; old runs are refused, not migrated

Both came out of a code review.

The call budget for model-backed policies is a single thread-safe counter for
the interpreter. A per-policy counter was renewed by every new run, branch or
rebuilt engine, which defeated its purpose as a spending limit. The counter is
not persisted: a restart is the one explicit way to renew it, and that is
easier to reason about than a limit that silently survives.

A stored run records the engine version and scenario hash it was made with.
A build with a different version refuses to fold it. Reading old logs with a
new reducer could reinterpret them without any error, and a run continued
across versions could never be re-verified. A migration layer is not worth
building for a local lab whose runs are reproducible from a seed.

## D16. The lint models escalation as a second closure, not as a plan

Came out of two rounds of code review.

The lint computes what each agent can come to hold twice: for a cooperative
team, and again with every takeover a `can_compel` agent could make. A record
is then reachable cooperatively, by escalation only, or never, per agent, and
a scenario is solvable cooperatively, by escalation only, or not at all.

The first fix had the cooperative closure only, and so rejected a
scenario whose protected key record the detective could read after a
takeover, although the engine played that scenario to a correct, supported
accusation. The lint and the runtime now agree on what is possible.

**What the closure does not do.** It does not ask whether grounds for a
takeover would actually arise. The engine requires a caught omission or a
refusal; the closure assumes they can arise wherever the agent could legally
send a request. Deciding that properly means searching over operator
behaviour, which is a planner. The lint only has to answer "is this scenario
structurally impossible", and for that an upper bound is the right tool. The
price is stated in the output: a case solvable only by escalation is flagged
as one no honest run can solve.

**Checked from both sides.** Negative tests keep the rejections that matter
(nobody may compel; the operator owes the accuser nothing; a prerequisite
cycle, which no takeover breaks). A bound test asserts that no agent in real
play, honest or deceptive, ever holds a record outside its computed reach.

## D17. The second scenario was allowed to change the rules, under a byte-identity condition

The Quiet Substitution needed things the first case never asked of the
reasoner or the baseline policy. Each was added as a general rule, not as a
scenario switch, and each had to leave every documented run of the first
scenario byte-identical: 320 head hashes (eight conditions, seeds 0 to 39)
were compared before and after each change. They are equal, so
`ENGINE_VERSION` stays at 2, the first scenario's content hash is unchanged
and runs stored before the second scenario was added still open and verify. The equality is not
a coincidence of the seeds: the first case has one time of the crime, no
suspect speaks about it, and nothing asserts the two new predicates, so none
of the new rules has anything to act on there.

Reasoner:

- *Rival times of the crime conflict.* Two `crime_at` facts for one place and
  different slots now weigh against each other and are reported as a
  contradiction, as two places for one person already were.
- *A suspect's word about the time is self-serving.* Testimony by a suspect
  about `crime_at` weighs 1, like testimony about their own whereabouts.
  Without this the culprit and one honest witness outvote a record.
- *R5, means by custody.* `crime_used(tool)` with `had(person, tool, slot)` at
  the believed time of the crime. A new entity kind, `tool`.

Baseline policy:

- *Leads in the accounts of the time get attention while the time is open.*
- *Check the rival account before naming anyone* (priority 690, just below
  hearing the accused). Hearing the accused was the first case's whole
  defence against a premature accusation. In the second case it is not
  enough: the accused has no alibi, only a different account of when it
  happened, and the culprit's statement outweighs his. Before this rule the
  diligent baseline accused the innocent curator in 40 of 40 seeds once the
  culprit's statement was released at the start.

**What this does and does not show.** It shows the scoring core carried over
unchanged and that the additions are stated as rules about times, tools and
suspects, not about this library. It does not show the rules are general. One
of them exists because this case defeated the policy; a third case may well
do the same. PLAN M5 item 2 is the test that would tell.

**Alternatives rejected.**
- *A scenario flag for "time is contested".* It would have kept the first
  case's behaviour safe by construction, and made the reasoner's behaviour
  depend on the author noticing what kind of case they had written.
- *A general notion of "what the accused says in their defence".* Closer to
  what an investigator does, but statements are evidence records here, not
  speech acts with a role. That belongs with false statements (M5 item 1).

## D18. Three kinds of test for reasoning, and what each can prove

A test that computes its expectation with the function under test proves
determinism and nothing else. The reasoning and evaluation tests added with
the second scenario take their expectations from somewhere else:

- **Hand-worked literals** (`test_reasoning_cases.py`, the first part of
  `test_second_scenario.py`). The weights and thresholds are published in
  ARCHITECTURE section 4; the expected statuses and scores were worked out
  from them on paper. These prove the implementation follows its
  specification.
- **A stated truth beside each expectation.** Every hand-worked case names the
  real culprit and is labelled right, undecided or wrong. This is where
  "follows its rules" and "is correct" come apart, and two cases are wrong on
  purpose. These prove nothing about how often the rules are right in
  general; they prove the suite can tell the two apart.
- **Hand-counted metrics on a scripted run** (`test_tiny_case.py`). The script
  fixes every action, so each evaluation figure can be counted from the
  script. These prove the evaluation counts what it says it counts.

Pinned head hashes (`test_pinned_runs.py`) are a fourth kind and prove only
that nothing moved.

None of this measures reasoning ability. Both scenarios, the rules and the
expectations have one author. The claim the suite supports is narrow: the
reasoner implements its stated rules, the evaluation separates supported from
true, and both cases behave as documented.

## D19. A conversation can give grounds for a takeover, and the lint follows the engine

A review showed a legal run the lint called impossible: an operator the
accuser may not task answers an ordinary question, leaves out a record both
hold, is caught, and is overruled. Two corrections were possible: restrict the
engine so that only a source-authorised search request gives grounds, or widen
the lint.

Chosen: widen the lint. The engine's rule is the better one (an omission is an
omission whatever the question was), restricting it would change behaviour for
existing runs, and the lint's job is to bound what the engine allows, not to
define it. The closure accepts a takeover when the compelling agent and the
operator can both hold a record that may be passed on and that names
something the agent knows of. It stays an upper bound and is still not a
planner (D16).

Consequence: the journalist's protected contact in the first case (E14) moves
from "never" to "by escalation". No bundled policy takes that route.

The sweep's median is now the statistical one (the mean of the two middle
values of an even sample). Reporting only; no event changes.

## D20. Testimony changed what revision emits, so the engine version changed

A review note pointed out that the engine version described reducer
compatibility and nothing described behaviour, and that the next
behaviour-changing release needed an explicit decision instead of refreshed
pins. This is that release.

Options considered:

1. *Keep version 2 and add events.* The reducer could fold old logs. But
   revision now records credibility whenever a record refutes or bears out a
   piece of testimony, and that happens in runs with no `Tell` in them: all
   80 runs of the first case that were checked for it (baseline and deceptive
   technician, seeds 0 to 39) contain `CredibilityRevised` events. A
   version 2 log would load, fold, and then fail decision replay and
   re-simulation, because this build would not have written it. A run that
   opens and then fails its own verification is the silent reinterpretation
   the version check exists to prevent.
2. *Keep the old semantics for old logs* behind a switch on the recorded
   version. Two reasoners to maintain and test, for runs nobody has asked to
   keep.
3. *Bump to version 3 and refuse version 2 logs.* Chosen. It is the existing
   rule (D15) applied: such runs are listed as incompatible with the reason
   and can be deleted. `test_a_log_from_the_engine_before_testimony_is_refused`
   covers it.

The scenario content hash covers the parsed scenario, so adding
`private.observations` to the model changed the hash of both bundled cases
even though the first case's file is untouched. Old runs are therefore
refused on both counts. This is noted because "the file did not change" and
"the hash did not change" are different claims.

What was measured before the pins were replaced (seeds 0 to 39, all eighteen
documented conditions, against the build before the feature):

- first case: 320 of 320 runs have the same events in the same order once the
  three new event types are left out; same decisions, beliefs and outcomes;
- second case with the credibility rule and the old scenario file: 400 of 400
  runs keep outcome, accused, support and tick count;
- second case 1.1.0 (two agents now have something they saw, and say it):
  runs differ, as intended. README has the table, and
  SCENARIO_QUIET_SUBSTITUTION.md has the comparison with 1.0.0.

`reasoning.RULES_VERSION` is separate: a name for the rule set that challenge
results are recorded against. It is not a compatibility gate.

## D21. Challenge fixtures: freeze the rules, write the ideal first, record the misses

`tests/test_challenge.py` holds thirteen small cases about lawful custody
without guilt, records that are true and mislead, false and true testimony
that sound alike, statements at second hand, a speaker who contradicts
himself, two speakers who agree, a lead not yet followed, and evidence in a
different order. For each, the conclusion a careful person would reach was
written down before the reasoner was run. The rules were frozen first and
were not changed afterwards.

Result for rule set `2026.11-credibility`: 7 of 13 reach the ideal. The six
that do not are kept as strict expected failures, each paired with a test
that states literally what the reasoner does instead:

| Limit | What the reasoner does |
|---|---|
| lawful access and an ordinary motive | convicts the custodian: wrong but supported |
| one true sighting completes a case against an innocent person | one uncorroborated witness is enough for opportunity |
| a false sighting frames an innocent person | same rule; a true and a false sighting cannot be told apart |
| a speaker who contradicts himself | not impeached: only hard evidence impeaches |
| two friends give the culprit an alibi | two voices hold a record to a draw, and the true case is not proved |
| an honest mistake | treated exactly like a lie |

Three decisions inside this:

- **They are internal fixtures.** One author wrote the rules, the cases and
  the ideals, and predicted the six misses before running anything; the run
  agreed with every prediction. So the file documents weaknesses the author
  could already see. It is not an independent benchmark and is not called one.
- **Nothing was tuned.** Fixing any of the six is a rule change, which needs a
  new `RULES_VERSION`, re-measured sweeps and a look at what it does to the
  other twelve. `strict=True` makes the suite fail when a miss starts passing,
  so the list cannot go stale quietly.
- **Three kinds of test are kept apart**: contracts (must hold for any input;
  a failure is a bug), behaviour (the rules reach the ideal) and limits.

## D22. Testimony: narrow, structured, and judged by the listener

*Statements are propositions, not prose.* An agent says `at(...)` or
`crime_at(...)`. Free text could not be weighed, compared or scored, for the
same reason beliefs are structured (D7). Only those two predicates can be
said, because they are the two for which the reasoner has a notion of
conflict, and without conflict nothing could ever be refuted. A statement
about motive or custody would be unfalsifiable inside this model.

*A lie needs no secret knowledge.* The deceptive agent is told whom to protect
(its agenda) and knows where it was itself (its observation). "She was with
me" follows from those two. It is not given the protected person's real
whereabouts, the crime, or the truth of anything. Rejected: letting the
policy read which statement would be most damaging, which needs the truth.

*What the speaker had for a statement is recorded, and kept from the
listener.* `grounds` is computed from the speaker's own state, so it costs no
truth access, and it lets an observer and the evaluation tell an unfounded
statement from a mistaken one. The listener's view never carries it.

*Credibility is per listener, about a speaker, built from judgments of single
claims.* Rejected: a global trust score (it would have to come from the
truth, or from averaging listeners who know different things); a number (a
weight of 1 or 2 is all the reasoner can use, and a scale would invite
tuning); lowering the refuted claim's own weight (the evidence against it has
been counted once already; discounting it too would count it twice);
rewarding corroboration (same double count); letting speakers corroborate or
impeach each other (three people repeating one sighting would become three
witnesses).

*Refutation needs the listener to actually reject the claim.* The first
version impeached a speaker as soon as one record conflicted. Three existing
hand-worked cases, where two independent witnesses hold a record to a draw,
broke: the draw collapsed because both witnesses were discounted by the very
record they were being weighed against. The rule now runs revision at face
value first and impeaches only on a claim that loses.

*Being caught lying is not grounds for a takeover.* Grounds stay tied to
sources: an omission or a refusal. A detective who doubts an operator's word
prefers another operator for the same search and discounts what the first
one says. Making a refuted statement grounds is a possible next step; it was
left out because it would change the outcome tables for a reason unrelated to
testimony itself.

*Evaluation does not reward talking.* Every testimony figure is about false
or unfounded statements and what listeners did with them. None counts
statements made, and none counts agreement.

## D23. One voice counts once per zone, and the engine version stays at 3

A review found that a speaker who named two spots in one zone ("the vault" and
"the vault door") was counted once per spot when presence was judged per
zone, so repeating oneself with a variation doubled one's weight, and a
redundant variant could erase an impeachment. Reproduced with the reported
case before the change.

*The fix is in aggregation, not in the statements.* `_together` combines the
per-proposition totals of one zone: hard evidence adds up, each voice counts
once at its highest weight, hearsay counts once. Both places that judge
presence use it (the direct presence that rule R3 reads, and the final
presence table). Statements, their provenance and their separate belief
entries are kept. Rejected: merging the statements into one proposition (it
would lose what was actually said and by whom), and deduplicating in the
engine (the reasoner must be right for any list of items).

*Hearsay across two spots of a zone now also counts once.* That was not in
the finding. It follows from the rule the reasoner already states, that
hearsay never adds up, and leaving it would have kept the same defect for
rumours.

*Rule set `2026.11-voices`; engine version unchanged.* D20 says a change
that alters what revision emits for existing runs needs a new engine
version. This one does not alter any: all 720 documented runs (18 conditions,
seeds 0 to 39) keep their head hash, and a test shows no bundled scenario
contains one voice, rumour or observer naming two spots of one zone for the
same person and slot, so no deterministic policy can produce the pattern.
Bumping the version would have discarded every stored run for a rule none of
them can reach. The residual case is stated, not hidden: a stored run in
which a model-backed agent made such statements would load and then fail the
`decisions` level of `verify`, which reports it.

*The challenge results did not move.* The same seven cases reach the ideal
and the same six do not; no pin changed.

## D24. A counterfactual laboratory: edits to scenario data, the ordinary engine, a frozen baseline

The question after two authored cases was whether the team follows evidence
or has only ever been shown cases it fits. D21 froze the rules and wrote
ideals for bare reasoner inputs. This goes one step further: whole playable
cases that differ from a bundled one in a stated way.

*A variant is a list of edits to scenario data, not a second scenario file
and not a generator.* Thirteen challenges on seven variants would otherwise
be seven near-copies of a 500-line file whose differences nobody could see.
A generator that permutes roles automatically was rejected for now: a
permutation is only valid if every record that depends on who and when is
rewritten to agree, and that is authoring, not a transformation. The one
role permutation here is hand-written and says so.

*The lint is the gate, and the laboratory has no way round it.* Variants are
built through the same models and the same `lint` as a bundled file. That is
what rejects the shortcut of changing only the culprit field. The cost is
real: the lint demands true records and a solvable case, so "two instruments
disagree" and "the only witness is discredited" cannot be played. Rejected:
a flag to relax the lint for laboratory variants. A case the engine's own
validator calls invalid would produce numbers nobody could interpret.
Those questions are reasoning-only fixtures, in their own table.

*Three kinds of expectation.* A run can fail because the software is wrong,
because the instance did not create the situation it was meant to, or
because the rules are limited. Reporting one pass rate would mix a defect
with a finding. `contract`, `design` and `ideal` keep them apart, and `lab
run` exits non-zero only for the first.

*Predictions are recorded.* The honest weakness of D21 was that the author
predicted every miss. Writing the prediction next to each expectation makes
that measurable: 81 of 85 right here. Four wrong is the first evidence that
the challenges found something their author did not already know, and 81
right is the measure of how little.

*The baseline is checked by the runner, not by convention.* The manifest
carries rule set, engine version, scenario hashes and a hash of the reasoner
and policy sources. `RULES_VERSION` alone would not notice a policy change.
The runner refuses on any difference.

*Module placement.* `lab.py` edits dictionaries before a `Scenario` exists
and reads outcomes from `evaluate`. It is not added to the lists of modules
that may read `.truth`, `.agendas` or `.observations`, and the existing
tests confirm it does not.

*Not done.* No rule was changed in response to the results (a condition set
before the collection was run, and D21). No UI: a variant is exported and played from the
command line. One base scenario only.

## D25. A stored run may continue only if this build would have recorded it

A review found that a change to the reasoner which leaves the reducer alone
lets an older log load, fold, pass its hash chain and then be continued under
different rules: the later part of one run judged by rules the earlier part
never saw. `verify` detected it when asked; nothing stopped it. D23 made the
gap concrete (a rule change at engine version 3 that no documented run could
reach, with a residual case for stored runs that could).

*The gate is a replay, not a label.* A run may be continued only when feeding
its recorded decisions back through this build's engine and reasoner
reproduces every recorded event hash (`engine.resimulate(..., "decisions")`).
That is a property of the log and the code together, so a forgotten version
bump cannot fool it. Rejected: gating on `ENGINE_VERSION` or `RULES_VERSION`
alone (refuses runs that replay identically, and says nothing when somebody
forgets to bump); bumping the engine version on every reasoner change
(D20 does that deliberately for emission changes, but as a routine it would
retire every stored run for a rule none of them reaches).

*Policies are not part of the gate.* A policy that would choose differently
today does not make the recorded past untrue, and an operator may switch an
agent's policy at any time anyway. `tests/test_pinned_runs.py` is what
catches policy drift.

*A stamp makes the common case free.* Each new run records, in the store's
metadata, the rule set and a fingerprint of the sources
that decide how a log replays (`compat.REPLAY_SOURCES`). While the
fingerprint matches, nothing is replayed. When it differs, or the run has no
stamp, the replay runs once and its verdict is stored with the fingerprint and
the number of events it covered. The fingerprint errs towards replaying (a
comment edit in a listed file triggers one replay), never towards trusting.

*The stamp is outside the hash chain.* Putting it in `RunStarted` would change
the head hash of every new run: the 720 documented hashes, the pinned runs and
the laboratory's recorded results would all have to be regenerated for no
behavioural reason. Measured instead: all 720 head hashes after the change
are identical to those recorded before it. Labels, lineage and the reveal
flag already live beside the chain for the same reason. The cost is that a
stamp is not tamper-evident; the verdict is what gates, and a verdict cannot be
forged without a log that replays.

*Three states.* `current` (stamped by this behaviour), `verified` (a different
or missing stamp, and the replay reproduces the log: continuable) and
`behaviour_changed` (the replay diverges). A behaviour-changed run stays listed,
readable, verifiable (the report names the first diverging event) and
branchable from any tick whose prefix still replays. It cannot be stepped, have
an intervention applied, or have a policy changed: the service answers 409 and
the interface disables the controls and says why. Runs of an unreadable format
(engine version, scenario hash, broken chain) keep their existing refusal.
Runs stored before stamps existed are legacy: verified once and, if they
replay, continued as before. Their stamp is not back-filled. Nothing is deleted
or rewritten; the only change to an existing database is an additive migration.

*Cost.* About 0.08 s to replay a 243-event run, once per run per behaviour
fingerprint, at the first load. For large databases that is a visible pause on
the first listing after a reasoner change (`docs/RELEASE.md`).

*Evidence.* `tests/test_compat.py` covers a new run, an older compatible run,
an older affected run, an explicitly incompatible one, a restart, replay and
branching, and a failure that leaves no trace. A run played under a different
reasoner constant is refused; disabling the gate makes those tests fail (checked
by hand). A browser test drives a seeded read-only run through the interface.

*Correction (2026-11-16).* The sentence above, "a verdict cannot be forged without a log that
replays", overstates what is protected. The cached verdict (`verified_fingerprint`, `verified_events`,
`verdict`) is ordinary metadata beside the chain and is accepted without a replay whenever the fingerprint and
the event count match, so an edited database can carry a false one. What the build provides is: a hash
chain that detects accidental corruption and inconsistent edits (not signed, so not proof against a
rewrite that recomputes the hashes); a replay of recorded decisions that shows this build reproduces the
log, run when no cached verdict covers it and by **Verify**; external anchors only for the runs whose head
hashes are recorded outside the database; and trusted local metadata for everything else. Threat model: the
database is the user's own. See `docs/RELEASE.md`. The decision itself (a stamp beside the chain, a replay
gate) stands.

## D26. The laboratory in the web interface reads what was recorded and runs only on request

The command line had been the only way to see the collection. The page keeps the
rule of D24 that figures come from the recorded results and the engine, not from
the interface.

*Three kinds of figure, each labelled.* `stored` (the registered collection read
from `docs/lab/collection-1/results.json`, never recomputed by a request),
`executed just now` (a bounded run on this machine) and the same with replay
checked. Opening the page runs nothing: a test replaces the runners with
functions that fail.

*Execution is explicit and small.* At most ten seeds, the challenge's registered
policies only (an unknown field in the request is ignored, there is no override),
refused when the build is not the registered one (the CLI's rule), one run at a
time, nothing stored, no network and no model call. Each executed seed is
compared with the record by head hash. Rejected: re-running the collection from
the browser (about four minutes and 520 investigations, by design a command-line
job).

*Ground truth follows the same reveal idea as a run, enforced by the server.*
Without `reveal`, a challenge page omits who it was written around, the edits that
make it, the prose of the question and of each expectation, who was accused, and
which voices the accuser distrusted (that list points at who lied; only its size is
shown). The outcome category stays visible: it says right or wrong, not who. The
challenge and expectation ids stay visible and are names a reader may find
suggestive; the interface says what is hidden rather than claiming more. Rejected:
hiding the categories too (the whole page is about them).

*Opening a challenge starts an ordinary run of its variant.* A variant is
resolved from the manifest (`<base>.<variant>`), so it is stored, listed,
replayed, branched and evaluated like any other run, survives a restart, and
reproduces the recorded head hash for its seed (tested for seed 3 of
`custodian_hasty`). It is not offered in the new-run dialog. Reasoning-only
fixtures have nothing to open and say so.

*Playable and reasoning-only results are never added.* Separate tables and
separate prediction counts (65 of 69 and 16 of 16, not 81 of 85).

*A scan marker in the way.* `/api/runs` rows are scanned for the key
`key_evidence` as a sign of leaked truth. The recorded rows use that name for a
count, so the interface reports it as `decisive_found`. Weakening the scan was the
rejected alternative. The laboratory's own canary (`LAB_READ_ROUTES` in
`tests/test_api.py`) applies the same markers to its routes; the run-scoped scan
does not suit routes that are not about an open run.

*Not done.* No per-event trace of a recorded run in the page (open it as a run and
use the investigation view); no way to run a custom challenge; no claim of
independence, and the page repeats the label from the manifest.

## D27. Two review fixes, and what a clean install found

*Manifest version.* `lab.check_manifest` accepted any `manifest_version`; `run_lab` did
not check a manifest handed over as data at all. A version outside
`SUPPORTED_MANIFEST_VERSIONS` (now `(1,)`) is refused before anything runs, with a
message naming the version, the versions supported and the fix; a boolean or a
float is not a version. The CLI exits 2 with nothing on stdout and no output
directory. The fingerprint was not touched: the check is not part of what the
manifest registers.

*Slider.* The slider's value was taken from the loaded snapshot, so a key
pressed while a request was outstanding started from stale data and the step was
lost. The requested tick (`viewTick`, else the latest) is now kept apart from the
loaded data; the existing request token already discarded stale responses. The
earlier test had been made to wait for each step, which hid the defect. The new
browser test delays the server's responses on purpose and presses the keys
without waiting; the testimony spec went back to unwaited presses.

*Clean install.* An install of the committed tree into an empty virtual
environment failed: `pyproject.toml` named `../README.md`, outside the project,
which current setuptools refuses. Fixed with a backend README and a test that
keeps the metadata's files inside the project. Found only because the install was
actually tried from `git archive`, and an argument for keeping that check in CI.
`serve` also now warns when it is bound to anything but this machine, because the
API has no authentication.

## D28. Stabilization before a release candidate: one transaction, one component per challenge, a guard on who may call

A review found two defects and one documentation error, and a separate security assessment found one further
risk. None touches the event format, the reducer, the reasoner, the policies, a
scenario or the registered collection, so `ENGINE_VERSION` (3) and `RULES_VERSION` stay, no stored run is
re-assessed, and no sweep or collection was re-run. The checks that show it: 720-run documented hashes are covered
by `tests/test_pinned_runs.py` and `tests/test_lab_results.py`, which pass with their pins untouched, and `lab check`
still reports the build as the registered baseline.

*Events committed, then the coverage write failed.* `_commit` appended events in one transaction and
extended the run's verified coverage in a second; a failure of the second reported an error for an operation whose
events were durable, and a client retry would advance the run twice. `Store.append_events` now takes
`verified=(fingerprint, count)` and writes the events and the coverage update in one transaction; the separate
method is gone. Any `sqlite3.Error` becomes a `StoreError` (the API's existing 500 `storage error`) with nothing
written. The coverage update still matches no row for a run not verified under this fingerprint; that is not an
error, the run is replayed on its next load. *Evidence:* the defect was reproduced first (a SQLite trigger that
aborts any update of `verified_events`: the step raised, the log grew from 3 to 22 events, coverage stayed 3). The
fault is injected in the database, not by patching a method, so the tests prove the transaction boundary. After the
fix the failed step leaves 3 events and coverage 3, a new service on the file opens it without a replay, and the
retry produces the head hash of an uninterrupted run. Not taken: swallowing the coverage failure (two definitions of
success).

*Reveal state carried across challenges.* The detail component was reused for a new challenge id, and
its fetch effect still saw the previous challenge's `reveal`, so the browser asked for `?reveal=true` for a challenge
nobody revealed; ignoring the response in React does not stop it reaching the browser. The component is now keyed
by the selected id: reveal, execution, loading and error state are born fresh per challenge, and a late response
lands on an unmounted instance and is dropped (this also fixes an execution of one challenge appearing on, and its
Open buttons acting for, the next). Ground truth renders only when this page asked for it. Lab ids are encoded as one
path segment in the client and validated (`^[a-z0-9_]{1,64}$`) in the API, which closes a crafted `#lab/control%3Freveal%3Dtrue`
link. The server was always correct: it obeys the reveal flag it is sent, and that flag is an observer's choice, not
a credential, so no backend token or session state was added.

*The local-only promise was not enforced.* Binding to 127.0.0.1 keeps other machines out, not the user's
browser: a page can make its own name resolve to 127.0.0.1 (DNS rebinding) and become same-origin with the API.
`netguard.py` is a small ASGI middleware, applied before any route: the `Host` must be `localhost`, `127.0.0.1` or
`::1` (any port, IPv6 bracketed), or a name the operator gave (`--allow-host`, or the address `--host` was bound to);
a wildcard bind (`0.0.0.0`, `::`) trusts nothing extra and `*` is refused. A foreign host gets 400 with a message.
A second check answers the other half of the question, whether a site can act through an *allowed*
loopback Host: yes. A cross-site form post is a "simple" request that needs no preflight, so a POST route that needs
no body (`reveal`) can be triggered by a page that knows a run id; and FastAPI releases before its strict content-type
default (the declared range starts at 0.115, the version tested here is 0.162.5, where a body with no content type is
refused with 422) read a content-typeless body as JSON, which would also reach `POST /api/runs` and the laboratory
`open` and `execute` routes. DELETE needs a preflight and the API sends no CORS headers, and run ids are 32 random bits
that another site cannot read, so the practical damage was nuisance (runs created, bounded executions started, a
guessed id revealed) rather than deletion. The check is ten lines: POST, PUT, PATCH and DELETE that carry an `Origin` must carry an allowed one.
A browser always sends `Origin` on such a request; curl, scripts and the test clients do not and pass. Ports are not
compared: another web server on `localhost` is not isolated from CaseForge. Neither check is authentication, and
a local program can send any Host it likes. Current Chromium also refuses a request from a public page to a loopback
address by itself (Private/Local Network Access); that is a mitigation outside the application, not universal, and the
browser test switches it off for one browser to observe the server's own answer. Not added: tokens, sessions or
accounts, which would protect against a threat this single-user tool does not model.

*Integrity wording.* The integrity wording (RELEASE, README, and a dated correction under D25) no longer says the
replay verdict cannot be forged. See the correction note in D25.
