# CaseForge Architecture

Status: describes the system as implemented. Rejected alternatives live in
[DECISIONS.md](DECISIONS.md); event contracts in [EVENT_MODEL.md](EVENT_MODEL.md).

## 1. Design goals and what they ruled out

The system is built around keeping six things apart: the truth of the case,
what each agent has observed, what it believes, the evidence it holds, the
actions it takes, and the evaluation of the outcome. That separation is what
makes a run measurable rather than a story. A deterministic baseline policy
that needs no language model keeps the domain model honest, and replay is a
requirement from the start rather than a feature added later.

Several obvious approaches were considered and set aside:

| Concern | Problem | Resolution |
|---|---|---|
| "Scripted toy" risk | If evidence carries author-written "supports hypothesis X" links, agents only add up the author's answer. | Evidence asserts *atomic propositions* (`at(person, place, time)`, `card_used(...)`). Suspicion is **derived** by scenario-independent defeasible rules. The scenario never says who an item incriminates. |
| Free-text beliefs | Beliefs as prose cannot be scored or compared against truth. | Beliefs are keyed by structured propositions with integer support/contra weights and a discrete status. Prose is display only. |
| "Full event sourcing" | CQRS, projections stores and snapshot stores are overhead for runs of a few hundred events. | One append-only event log per run plus a pure reducer. State is a fold. No snapshot store (see D1). |
| Graph database | The graph has ~100 nodes and no query that Python cannot do in microseconds. | The graph is a pure projection of state, computed on request (D2). |
| Exhaustive search | If agents may inspect "everything they can access", every run converges to the same full evidence set and nothing is measurable. | Sources are *queried by topic*. Agents must choose what to look for, and leads (entities mentioned in held evidence) drive those choices. Seeds and interventions therefore change outcomes. |
| LLM replay | "Deterministic replay" of a model call is not a thing. | Two separate guarantees: replay-by-fold (always holds) and re-simulation (deterministic policies only). See section 5. |
| Composite scores | A weighted "investigation score" is unfalsifiable. | Every metric is a count with an explicit denominator. No blended score (D6). |
| Tailwind | A build plugin for ~500 lines of CSS. | One hand-written stylesheet with CSS variables (D3). |

**Scope.** The first version was deliberately small: one well-constructed
scenario, a rule-based reasoner, four agents with distinct access and
dispositions, replay, time travel, branching, interventions, objective
evaluation, and a control-center UI. A second scenario, testimony and the
counterfactual laboratory came later. Scenario authoring tools, verification
sub-actions and an LLM judge are still not built.

**Complexity that had to be planned for.**

1. *Scenario consistency.* A mystery whose "solution" does not follow from its
   evidence invalidates every metric. The scenario is linted mechanically
   (section 6) and a test proves the reference reasoner reaches the culprit.
2. *Nondeterminism leaks*: set iteration, `hash()` randomization, wall-clock
   time, UUIDs, float formatting, `random` API drift between Python versions.
   All removed by construction (section 5).
3. *Truth leakage*: through agent views, through event payloads, through the
   API, and through identifiers themselves. Evidence ids are opaque (`E07`),
   and each path has an adversarial test.
4. *Belief provenance.* Knowing *why* a belief changed requires recording the
   change as an event with its triggering evidence, not recomputing it later.

## 2. System shape

```
                 +--------------------------------------------+
  scenario.json  |  Scenario = public part + private part      |
  --------------►|  (private: evidence bodies, world truth)    |
                 +---------------------+----------------------+
                                       |
        +------------------------------v-----------------------------+
        |                        Engine (tick loop)                   |
        |                                                             |
        |  state --build_view--► AgentView --Policy.decide--► Action  |
        |    ▲                   (only what the                |      |
        |    |                    agent holds)                 ▼      |
        |    |                                         validate(action)|
        |    |                                                 |      |
        |    +---- apply_event ◄---- events ◄---- effects -----+      |
        |                              |                               |
        +------------------------------+-------------------------------+
                                       | append-only, hash-chained
                              +--------v--------+
                              |  SQLite: events  |
                              +--------+--------+
                                       | fold
              +-----------+------------+-----------+-------------+
              ▼           ▼                        ▼             ▼
         SimState     graph projection       evaluation       API / UI
        (any tick)   (per perspective)    (reads truth)   (observer view)
```

A single Python process. No queues, no actors, no background workers. The API
is a thin shell over the engine; the UI talks only to the API.

## 3. Module boundaries (`backend/caseforge/`)

| Module | Responsibility | May read private scenario data? |
|---|---|---|
| `canon.py` | Canonical JSON, hash chain, hash-derived deterministic choice | no |
| `models.py` | Pydantic contracts: scenario, propositions, actions, events | defines them |
| `scenario.py` | Load, validate and lint scenarios | yes (lint only) |
| `reasoning.py` | Belief revision, derivation rules, suspect scoring. Pure. | no. Input is a list of evidence items |
| `state.py` | `SimState` and the pure reducer `apply_event` | no |
| `views.py` | **The observation gateway**: builds `AgentView` | resolves bodies of *held* evidence only; hands an agenda and what an agent saw for itself to their owner |
| `actions.py` | Action validation and effect computation | yes (it is the world) |
| `policies/` | `Policy.decide(view, rng) -> Decision` | **no**. Receives `AgentView` only (which carries the agent's own agenda, if it has one) |
| `engine.py` | Tick loop, interventions, branching, verification | yes |
| `evaluation.py` | Deterministic metrics against truth | yes, the only consumer of `truth` besides lint |
| `compat.py` | Whether a stored run may be continued by this build: a replay verdict, a stamp beside the hash chain (section 9) | no. Reads events and the scenario through the engine only |
| `lab_service.py` | The laboratory as the web interface reads it: recorded results, the reveal gate, bounded re-runs (DECISIONS D26) | reads the manifest's own statement of the design (culprit, edits), withheld unless asked for; never `.truth` |
| `lab.py` | Counterfactual laboratory: builds variants from scenario data, runs challenges, aggregates, reports (docs/LAB.md) | edits scenario *data* as an author would, before a `Scenario` exists; reads outcomes only from `evaluation` |
| `graph.py` | Knowledge-graph projection | discovered evidence only |
| `narrate.py` | One-line descriptions of events | titles of evidence the event itself delivered |
| `observer.py` | What the API may show a human: the union of agent knowledge | discovered evidence only |
| `store.py` | SQLite persistence. `append_events` writes the events and the extension of the run's compatibility coverage in one transaction (DECISIONS D28) | no |
| `service.py` | Coordinates engine and store; gates evaluation and the truth overlay | truth values, only once a case is closed or revealed |
| `api.py` | FastAPI routes | via the service only |
| `netguard.py` | Who may talk to the local API: a Host allow-list (DNS rebinding) and an Origin check on state-changing methods (DECISIONS D28). Not authentication | no |

**Dependency rule:** `policies/*` import only `models`, `canon`, `reasoning`
(pure, truth-free) and each other. A test asserts this by parsing their
imports. A second test finds every syntactic access to `.truth` and fails if
any module other than `scenario.py`, `evaluation.py` and `service.py` has one.
A third does the same for `.agendas` (allowed: `scenario.py`, `views.py`,
`observer.py`, `evaluation.py`, `service.py`), and a fourth for
`.observations` (allowed: `scenario.py` for the lint, `views.py`).

## 4. Knowledge model

**Propositions** are typed tuples over a fixed predicate vocabulary:

| Predicate | Meaning |
|---|---|
| `at(person, location, slot)` | person was at location during a time slot |
| `crime_at(location, slot)` | the theft happened there and then |
| `card_used(card, location, slot)` | credential presented at a reader |
| `card_holder(card, person)` | registered holder |
| `card_cloned(card)` | a duplicate of the credential exists |
| `card_written(card, location, slot)` | a duplicate was encoded there and then |
| `has_motive(person)` | person had a reason to take the object |
| `took(person, object)` | direct assertion of guilt (rumors, published claims) |
| `could_use(person, card)` | *derived only*: person could have presented the card |
| `crime_used(tool)` | the crime was committed with this tool (a key, say) |
| `had(person, tool, slot)` | person had custody of the tool during a time slot |

**Evidence** asserts zero or more propositions and has a *kind* that fixes its
base weight: `forensic` 5, `record` 4, `testimony` 2 (1 when a suspect speaks
about their own whereabouts or about the time of the crime, since moving the
time moves the suspicion), `hearsay` 1. Hearsay never stacks: ten rumors
weigh the same as one. Records cannot be forged; statements can be false.

**Six things that are kept apart.** The reasoner's input is a list of items,
and each item says which of these it is:

| | What it is | Where it comes from | Weight |
|---|---|---|---|
| Evidence record | an authored record an agent holds | a source, a share, an intervention | by kind, above |
| Observation | what an agent saw for itself (`O1`, `O2`, ...) | `private.observations`, delivered to its owner only | 4, counts as hard evidence |
| Direct testimony | what another agent told this one on its own word (`S<seq>`) | a `Tell` action | 2, or 1 (below) |
| Passed-on testimony | another agent's report of what a third said | a `Tell` with `heard_from` | never more than the listener gives hearsay; counted as the first speaker's voice |
| Belief | what one agent concludes from its items | `revise`, recorded as `BeliefsRevised` | derived |
| World truth | what happened | `private.truth` | never an input |

A statement never becomes a fact by being made, repeated or believed. It is
one more item, and it is weighed against the others each time anything new
arrives.

**Voices.** Testimony is counted per voice, not per hearing: the same person
saying the same thing in a record, to me, and through someone who passes it
on, is one voice with its highest weight. Three people repeating what one of
them saw are one voice.

**Beliefs.** For agent *a* and proposition *p*: `support` is the aggregated
weight of held evidence asserting *p* plus active derivations; `contra` is the
weight behind propositions that conflict with *p* (two `at` facts for the same
person and slot in different zones; two `crime_at` facts for the same place at
different times). `net = support - contra` gives the status:
`believed` (net >= 2), `rejected` (net <= -2), `disputed` (contested and
undecided), `tentative` (weak and uncontested).

**Derivation rules** (scenario-independent, all defeasible):

- R1 `card_used(C,L,t)` and `card_holder(C,P)` imply `at(P,L,t)`, *unless*
  `card_cloned(C)` is believed.
- R2 `card_written(C,..)` implies `card_cloned(C)`.
- R3 `card_written(C,L,t)` and `at(P,L,t)` imply `could_use(P,C)`.
- R4 `card_used(C,L,t)`, `card_cloned(C)` and `could_use(P,C)` imply `at(P,L,t)`.
- R5 `crime_used(T)` and `had(P,T,t)`, with `t` the *believed* time of the
  crime, give P the means. While the time is disputed R5 gives nobody
  anything.

R1 to R4 are about access cards and R5 about a tool in someone's custody. The
rest (weights, conflicts, alibi, motive, scoring, the standard) is shared.
What the two bundled cases exercise is listed in the module docstring of
`reasoning.py`; no claim is made for mysteries of another shape.

**Suspect score** (integer, per agent, per suspect): opportunity +3 (weak +1),
alibi -4, means +2, motive +2 (weak +1), named by hearsay up to +2. An agent's
*disposition* scales the hearsay weight and sets its publish threshold, so two
agents holding the same evidence can disagree.

**Standard of proof.** Strong opportunity, means, and a *believed* motive
(hearsay alone gives a weak motive and does not qualify), with a lead of at
least 3 over every other suspect. Being named, by however many voices, counts
toward ranking and never toward the standard. The baseline detective accuses
only when the standard is met, the accused has been heard, and no rival
account of the time of the crime names a lead she has not followed. The same
standard, applied by a neutral reference reasoner to what a speaker held at
the time, is what evaluation means by "supported". Supported is not the same
as right: both bundled cases contain a set of genuine records that meets the
standard against an innocent person, and tests pin those sets down.

Belief revision is run by the engine after every delivery of information and
its result is **recorded** as a `BeliefsRevised` event with the triggering
evidence. The reducer applies recorded diffs; it never recomputes. A test
asserts that recomputing from holdings matches the recorded state.

**Credibility.** Defined in the docstring of `reasoning.py`; in short:

- *Of a claim, for one listener.* A spoken claim is **refuted** when the
  listener holds hard evidence (record, forensic, own observation) for a
  conflicting statement, none for the claim, and rejects the claim when
  everything is weighed at face value. It is **corroborated** when hard
  evidence supports it, none conflicts, and the listener believes it.
  Otherwise it is unchecked.
- *Of a speaker, for one listener.* **Impeached** once one claim is refuted;
  **corroborated** when some were checked and none failed; otherwise no entry.
- *Effect.* An impeached speaker's other claims weigh 1, which is below the
  threshold for belief, so nothing is believed on that speaker's word alone.
  The refuted claim keeps its weight (the evidence against it was already
  counted once) and corroboration adds nothing (same reason).

Revision therefore runs in two passes: face value, assess the speakers, then
again with impeached voices capped. Credibility is never a number, never
global and never informed by the truth: it follows from what the listener
holds, so two listeners can judge one speaker differently, and a listener
with no hard evidence on the point judges nobody. Only hard evidence moves a
standing; agreement between speakers does not corroborate and one speaker's
word does not impeach another. A standing can be lost again, in either
direction, when the evidence behind it is outweighed.

Nothing is rewritten. Each change of a listener's stance on a statement
(`StatementWeighed`) and of its view of a speaker (`CredibilityRevised`) is an
event at the tick it happened, so the state at an earlier tick still shows the
statement as accepted if it was accepted then.

## 5. Replay semantics

Two distinct guarantees. Conflating them is the classic mistake.

1. **Replay (fold).** `state(n) = fold(apply_event, initial, events[0..n])`.
   Holds for every run, including LLM-driven ones, because decisions and belief
   changes are stored as events. Replay never calls a policy or a model.
2. **Re-simulation.** For runs using only deterministic policies, re-running
   the engine from `(scenario hash, seed, intervention schedule)` produces a
   byte-identical event log. `verify` checks this by comparing head hashes.

How nondeterminism is excluded:

- **Time** is the integer tick. Events carry no wall-clock data. Run creation
  time lives in the `runs` table, outside the hashed log.
- **Identity.** Event id is its `seq`. Claim and request ids derive from the
  seq of the creating event. Run ids are random but never enter the log.
- **Randomness** is counter-based: `sha256(seed | tick | agent | purpose)`.
  There is no RNG state to checkpoint, so branching needs no RNG snapshot, and
  no dependence on `random` module internals.
- **Ordering.** Every iteration over a set or dict that can reach an event is
  sorted. A test runs the simulation under two different `PYTHONHASHSEED`
  values and compares hashes.
- **Numbers** are integers. No floats enter the log.
- **Hash chain.** `event.hash = sha256(prev_hash + canonical(event))`. The head
  hash identifies a run's entire history; a shared prefix identifies a branch
  point.

**Checkpoints and branching.** Every tick boundary is an implicit checkpoint.
`branch(run, tick)` copies the event prefix into a new run with `parent_run_id`
and `fork_seq`. Because randomness is counter-based, an unperturbed branch
reproduces its parent exactly; divergence comes only from interventions or a
different policy assignment.

## 6. Ground-truth isolation

- The scenario file has two top-level parts. `public` holds the briefing,
  entities, agents, sources and intervention labels. `private` holds evidence
  bodies and the `truth` block.
- A policy receives an `AgentView`: a deep-copied Pydantic model built from the
  agent's own state. Evidence bodies are resolved through one function that
  refuses ids the agent does not hold.
- The observer API exposes the union of what agents know. Undiscovered evidence
  appears only as a count. `truth` and truth-dependent metrics are served only
  when the case is closed or the user explicitly reveals the solution.
- Isolation is by interface, not by sandbox: policies run in-process. That is
  stated plainly rather than oversold.
- **Scenario lint** (`caseforge validate`) checks that truth is self-consistent
  (one location per person per slot), that `record` and `forensic` evidence
  only asserts true propositions, that every false assertion is `testimony` or
  `hearsay`, that every source and topic reference resolves, that every record
  can be acquired under the engine's own access rules, and that the records an
  accuser can come to hold meet the standard of proof for the culprit. Reach
  is computed twice, for a cooperative team and with the takeovers a
  `can_compel` agent could make, and reported per accuser. See SCENARIO.md
  for what the acquisition check does and does not prove.

### Deception

One agent may work against the investigation. The design keeps four things
apart:

- **Private knowledge.** `private.agendas` gives an agent a commitment: whom
  it protects, whom it deflects suspicion to, whom it feeds. It is delivered
  to that agent's view only. The observer API shows its text only for an
  unlocked run, like the solution (but see *Physics* below for what the
  decision trace gives away). A model-backed policy is never shown it.
- **Behaviour.** Only the `deceptive` policy acts on an agenda. It uses
  ordinary actions: a `Respond` with `withhold_about` set, a refusal to
  volunteer, a `Share` to the journalist. Nothing it does bypasses validation.
- **Physics.** A withheld record is looked at and kept (`EvidenceWithheld`).
  The requester's view gets a normal answer listing what was delivered, and
  nothing else. The observer does see the event: what an agent did is agent
  knowledge. Its decision trace says "private agenda" and names the protected
  person, so a user who assigns the policy can infer the agenda's gist from
  the timeline; the agenda's text and the solution stay locked.
- **Detection.** The engine emits `DiscrepancyNoticed` when a requester comes
  to hold a record that the logged search behind an earlier answer had found
  and not delivered. The comparison is against the log, so it is exact: an
  honest empty answer is never flagged. An agent with `can_compel` may then
  `Escalate` against that operator, which opens every source he runs to it
  (`AccessEscalated`). A refused search request is grounds too.

Limits, stated plainly. Detection is engine-assisted: an agent reasoning only
from its view could not rule out that a record became retrievable later.
A caught operator is bypassed, not removed: the compelling agent gains direct
access to his sources and he keeps operating them. Being caught leaving a
record out does not by itself lower the weight of what he says; that takes a
refuted statement (below).

### Testimony and false statements

`Tell(to, proposition)` says something to one other agent on the speaker's own
word. `Tell(..., heard_from=X)` passes on what X told the speaker.

- **What may be said.** Two predicates, `at` and `crime_at`: where someone
  was, and when it happened. Every entity named must be known to the speaker.
  A statement is said once per recipient. The engine checks form and never
  truth: a false statement is a legal action.
- **What the speaker had for it** is recorded on the event as `grounds`:
  `observed` (it saw this), `held` (a record it holds asserts it, listed in
  `backing`), `heard` (it is passing on a statement it received) or `none`.
  This is derived from the speaker's own state, so recording it needs no
  truth. The recipient is told the statement, the speaker and, for a relay,
  whose word it is. It is never told the grounds.
- **Honest agents** state only what they saw, to those they report to, and
  pass on what they are told to the same people. An implicated agent tells the
  accuser where it was.
- **The deceptive policy** builds an alibi from two things it legitimately
  has: its agenda (whom to protect) and its own observation of where it was
  itself. It says the protected person was there with it. It is given no fact
  about where that person really was, and needs none. The statement is a pure
  function of view, seed and tick, like every other decision.
- **Detection** is the credibility rule above, in the listener's head, from
  the listener's evidence. Unlike the detection of withheld records it is not
  engine-assisted.

Limits, stated plainly. No statement about motive, custody or guilt can be
made in this way. Statements are not retracted. A speaker caught lying is
discounted and, if it operates sources, searched around where another
operator exists; a lie is not grounds for a takeover. The reasoner cannot tell
a lie from an honest mistake. More are listed with the challenge fixtures
(`tests/test_challenge.py`, DECISIONS D21).

## 7. Graph projection

`project_graph(state, perspective)` returns nodes and edges; nothing is stored.
Ontology: nodes `person`, `location`, `object`, `evidence`, `proposition`,
`claim`, `statement`; edges `observed`, `received`, `communicated_to`,
`reported`, `supports`, `contradicts`, `cites`, `associated_with`,
`located_at`, `suspects`, `accused`, `distrusts`, `addressed`, `relays`,
`witnessed`, `doubts` (the authoritative list is the docstring of `graph.py`).
A statement node carries what its speaker had for it only in the combined view
and in the speaker's own, and the listener's stance only in the combined view
and the listener's own.
Perspective is `all` (observer) or one agent (only what that agent holds, with
its belief status on each proposition node). A proposition node is never
marked "true": it only carries per-agent belief status.

Every edge carries the `seq` and tick of the event that created it. For edges
that come from reasoning (derivations, suspicion, contradictions) that event
is recorded by the reducer when the `BeliefsRevised` or
`ContradictionRecognized` event is applied, together with the event that last
changed the edge (`changed_seq`). The projection never dates anything with the
head of the log, so a relationship does not move when unrelated events arrive.

The combined view does not merge agents' reasoning. A derivation edge has an
`agents` map with each holder's own `active` flag and event references, and a
`state` of `active`, `defeated` or `mixed`; `mixed` means the agents disagree
and `active` is then null.

## 8. Future compatibility

- **GraphRAG.** The projection already yields typed nodes, typed edges and
  provenance. Exporting it as triples, or indexing evidence bodies for
  retrieval by an LLM policy, needs no model change.
- **Agent orchestration frameworks.** `Policy.decide(view, rng)` is the only
  seam. A LangGraph or similar agent can sit behind it; the engine still
  validates and records every action.
- **Evaluation frameworks.** `evaluate()` returns plain counts with
  denominators; `caseforge sweep` emits one JSON row per seed, which is the
  shape eval harnesses consume.

## 9. Stored-run compatibility

The hash chain checks that a log is internally consistent (it is not signed; see docs/RELEASE.md for what that does
and does not protect). It says nothing about whether this build would have recorded the log:
beliefs in the log were computed by whichever reasoner was running. `ENGINE_VERSION` guards the format; it cannot
guard behaviour. DECISIONS D25 has the reasoning; the shape is:

```
load run -> chain intact? -> engine/scenario readable? -> assess(run)
                                                        |
        stamp.fingerprint == behaviour_fingerprint()? --+-- yes, and a stored verdict covers it: current
                                                        |
                                                        +-- otherwise: resimulate(decisions) once, store the verdict
                                                                 reproduces all events -> verified   (continuable)
                                                                 diverges              -> behaviour_changed (read-only)
```

* The fingerprint covers `compat.REPLAY_SOURCES` (`reasoning`, `engine`, `actions`, `state`, `views`, `models`). It
  deliberately excludes the policies.
* The stamp (rules version and fingerprint; the engine version is already stored with the log) and the verdict (fingerprint, events covered, ok or diverged,
  first divergence) live in the `runs` table, never in an event: `RunStarted` is unchanged, so no head hash moved.
* `RunService._require_continuable` guards step, intervention and policy change (409, `ContinuationRefused`);
  `branch` allows a tick whose prefix still replays.
* The summary of every run carries `continuable` and `compatibility` (state, stamped and current rules, first
  divergence, a sentence); the interface shows a banner and disables the controls.
* Additive migration only. Legacy runs (no stamp) are verified once and not back-filled. Nothing is rewritten.
