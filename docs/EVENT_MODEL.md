# Event Model

The event log is the only source of truth for a run. Contracts live in
`backend/caseforge/models.py` (`EVENT_TYPES`); the reducer is
`backend/caseforge/state.py`.

## Envelope

```json
{
  "seq": 42,              // position in the run, starting at 0; also the event's identity
  "tick": 3,              // simulation time; 0 is setup
  "type": "EvidenceShared",
  "actor": "reyes",       // an agent id, "engine" or "user"
  "cause": 40,            // seq of the event that led to this one, or null
  "data": { },            // payload, validated against the type's contract
  "hash": "9f2c..."       // sha256(previous hash + canonical JSON of the six fields above)
}
```

Payloads contain strings, integers, booleans, lists and objects only. No
floats, no wall-clock values, no random identifiers. Canonical JSON is sorted
keys, no whitespace, ASCII.

## Event types

| Type | Actor | Payload | Effect on state |
|---|---|---|---|
| `RunStarted` | engine | scenario id, version and hash, engine version, seed, agents, policies, max ticks | creates empty agent states |
| `TickStarted` | engine | `order` | records the turn order |
| `ActionTaken` | agent | `agent`, `action`, `trace` | counts the action; effects follow as separate events |
| `ActionRejected` | agent | `agent`, `action`, `trace`, `code`, `message` | counts the rejection; nothing else changes |
| `SourceInspected` | agent | `agent`, `source`, `topic`, `found`, `new`, `on_behalf_of` | remembers the query (own-initiative queries only) |
| `EvidenceObserved` | agent | `agent`, `evidence`, `source`, `via` | agent holds the record first-hand; first discovery is noted |
| `EvidenceShared` | agent | `sender`, `recipient`, `evidence`, `context` | recipient holds a copy; custody chain is extended |
| `EvidenceReleased` | user | `evidence`, `recipient`, `intervention` | recipient holds the record via an intervention |
| `RequestSent` | agent | `request`, `sender`, `recipient`, `topic`, `source` | a pending request exists |
| `RequestAnswered` | agent | `request`, `by`, `outcome`, `evidence` | request becomes fulfilled, nothing_found or declined |
| `EvidenceWithheld` | agent | `request`, `by`, `requester`, `evidence`, `about` | the request remembers what was found and not handed over; never part of the requester's view |
| `DiscrepancyNoticed` | agent | `agent`, `against`, `request`, `evidence` | the agent has caught that answer leaving that record out |
| `AccessEscalated` | agent | `agent`, `source`, `against`, `grounds` | agent may query the source directly; it has gone over that operator's head |
| `StatementMade` | agent | `statement`, `speaker`, `recipient`, `proposition`, `origin`, `relays`, `grounds`, `backing` | the statement exists; `grounds` and `backing` are what the speaker had for it and never enter the recipient's view |
| `StatementWeighed` | agent | `agent`, `statement`, `stance`, `belief` | appends to the listener's path for that statement: `accepted`, `questioned` or `rejected`, with the belief status behind it |
| `CredibilityRevised` | agent | `agent`, `speaker`, `credibility`, `before`, `because` | the listener's view of that speaker is replaced (`null` removes it); the change of standing is kept in a history |
| `ClaimPublished` | agent or user | `claim`, `by`, `proposition`, `cited`, `audience`, `text` | claim exists; each listener has heard it |
| `ClaimRetracted` | agent | `claim`, `by` | claim no longer counts for listeners |
| `BeliefsRevised` | agent | `agent`, `because`, `changes`, `suspects`, `prime_before`, `prime_after` | applies the belief diff and new suspect assessments |
| `ContradictionRecognized` | agent | `agent`, `a`, `b` | the pair is remembered, even after it is resolved |
| `InterventionApplied` | user | `intervention`, `kind` | intervention is marked used |
| `AccessGranted` | user | `agent`, `source`, `intervention` | agent may query the source directly |
| `PolicyChanged` | user | `agent`, `policy` | agent follows a different policy from now on |
| `AccusationMade` | agent | `by`, `suspect`, `cited` | the accusation is recorded |
| `CaseClosed` | engine | `reason` (`accusation` or `tick_limit`) | status becomes closed |

Request ids are `R<seq>`, claim ids `C<seq>` and statement ids `S<seq>`, where
`seq` is that of the creating event. They are stable without a counter.
Observation ids are `O1`, `O2`, ... in the order the scenario lists them for
an agent, and are local to that agent. Evidence ids of that shape (`C`, `O`,
`R` or `S` followed by digits) are rejected by the lint.

## One agent's turn

```
build_view(state, agent)                  only what the agent holds
policy.decide(view, rng)                  -> action + trace
validate_action(...)   --fails-->  ActionRejected              (turn ends)
                       --passes--> ActionTaken (seq s)
apply_action(...)                         effect events, cause = s
revise beliefs of everyone who learned    BeliefsRevised, ContradictionRecognized,
                                          CredibilityRevised, StatementWeighed, cause = s
notice omissions now visible              DiscrepancyNoticed, cause = s
```

A `Tell` produces one `StatementMade`. The recipient's revision then records a
`StatementWeighed` for it, whatever the stance, so every statement has a first
reaction on the log. Later revisions record another `StatementWeighed` only
when the stance changes, and a `CredibilityRevised` only when the listener's
view of a speaker changes. `stance` follows the listener's belief in the
proposition: believed is `accepted`, rejected is `rejected`, anything else is
`questioned`.

An answer to a request is `SourceInspected` (what the search found), one
`EvidenceShared` per record handed over, `EvidenceWithheld` if the responder
kept any back, then `RequestAnswered` with what was delivered. A requester
"notices" when it holds a record listed in the `EvidenceWithheld` of an answer
it received: either at once, if it already held the record when it asked, or
later, when the record arrives by another route.

A tick is `TickStarted`, then one turn per agent in the order
`shuffle(agents, seed, tick)`, then `CaseClosed` if the tick limit is reached.
An accusation ends the tick immediately.

`BeliefsRevised.changes` maps each proposition whose entry changed to its new
entry, or to `null` if it was dropped. `because` lists the evidence or claim
ids that just arrived. The reducer applies this diff; it never recomputes
beliefs. A test checks that recomputing from holdings gives the same result.

## Replay guarantees

1. **Fold.** `state(n) = fold(apply_event, events[0..n])`. The reducer needs
   no scenario file. It rejects gaps and reordering.
2. **Chain.** Each hash covers its predecessor, so any edit, removal or
   reordering is detected at the first affected event.
3. **Decision replay.** Feeding the recorded actions back through validation,
   effects and belief revision reproduces the log byte for byte. This holds
   for every policy, including model-backed ones.
4. **Re-simulation.** Running the policies again from the seed reproduces the
   log byte for byte. This holds for deterministic policies and is reported as
   skipped otherwise.

`GET /api/runs/{id}/verify` and `caseforge demo` run all four.

What a run depends on, completely: scenario content hash, engine version,
seed, initial policy assignment, and the sequence of user operations
(`step`, `intervene`, `set_policy`). Nothing else.

## Time travel and branching

- The state at tick *k* is the fold of events with `tick <= k`. An
  intervention made after tick *k* and before tick *k+1* carries tick *k*.
- A branch copies that prefix into a new run with `parent_run_id` and
  `fork_tick` stored in the `runs` table. Lineage is metadata and is not in
  the log, so an unperturbed branch has the same hashes as its parent.
- Randomness is `sha256(seed | tick | agent | purpose)`. There is no generator
  state, so a branch needs nothing but the event prefix.
- A case that is already closed at the chosen tick cannot be branched there.

## Persistence

`events(run_id, seq, tick, type, actor, cause, data, hash)` with primary key
`(run_id, seq)`. An operation's events are written in one transaction after
the operation completes in memory. On any failure the in-memory engine is
discarded and reloaded from the last stored event, so a run on disk is always
a whole number of operations.

## Versioning

`RunStarted` records the scenario content hash and the engine version.
`check_compatible` (in `engine.py`) compares both with the running build
before a stored log is folded, and raises `IncompatibleRun` on a mismatch.
There is no migration and no read-only mode for old logs: a reducer from
another version could misread a log without failing, so the run is refused
outright. Through the API such a run still appears in the run list, with
`compatible: false` and the reason, and can be deleted; every other operation
on it answers 409. The service also checks the hash chain when it loads a run
from disk; a log that fails its own chain is treated the same way.

Changing reducer behaviour for an existing event type requires bumping
`ENGINE_VERSION`. History:

| Version | Change |
|---|---|
| 1 | Initial reducer. |
| 2 | `BeliefsRevised` and `ContradictionRecognized` also record provenance stamps (which event introduced and last changed each belief, derivation, contradiction and prime suspect). State only; payloads are unchanged. |
| 3 | Testimony and credibility. New events `StatementMade`, `StatementWeighed`, `CredibilityRevised`; new state (`SimState.statements`, `AgentState.credibility`); an agent's own observations are information it revises on from the start. Revision now also emits credibility events in runs that contain no `Tell` (a record can refute testimony that is itself a record), so a version 2 log is not what version 3 would have written for the same run. Version 2 logs are refused (DECISIONS D20). |

Not every change needs a new version. Adding the second scenario brought two
predicates, an entity kind, reasoner rules and policy steps, and kept version 2, because the reducer is untouched and every
documented run of the first scenario kept its head hash (DECISIONS D17).
`tests/test_pinned_runs.py` holds reference hashes for both scenarios. A
change to a policy or to the reasoner that moves them leaves the reducer
compatible but makes runs stored earlier fail the re-simulation levels of
`verify`; that is reported by `verify`, not prevented by the version check.

Two identifiers, two jobs. `ENGINE_VERSION` says which logs this build can
fold and continue; it is stored in every log and enforced on load.
`reasoning.RULES_VERSION` names the rule set (weights and rules) that the
results in `tests/test_challenge.py` are recorded against. It is not stored in
a log. It is stamped beside each run in the store (with a fingerprint of the
replay sources), and still gates nothing by itself: continuing a run is gated
by a replay of its recorded decisions (DECISIONS D25). Rule set
`2026.11-voices` changed the rules only ( one voice counts once per zone, not once per spot it
names; DECISIONS D23) and left the engine version at 3, because no run a
deterministic policy can produce on a bundled scenario reaches the changed
rule, and all 720 documented runs kept their head hash. The counterfactual
laboratory's manifest records both identifiers, and a fingerprint of the
reasoner and policy sources, and refuses to report under any other
(docs/LAB.md). Testimony changed both: the credibility rule changes what
revision emits, so the engine version moved with it instead of leaving
version 2 runs to load and then fail re-simulation.

The stored-run compatibility check (D25) changed no event type, field or
reducer rule, and `ENGINE_VERSION` stayed at 3. The `runs` table gained nullable columns (`rules_version`, `fingerprint`, `verified_fingerprint`, `verified_events`,
`verdict`, `divergence`, `verdict_detail`) by an additive migration; an old database opens unchanged and its runs are
treated as legacy. These columns are metadata beside the chain, like the label and the reveal flag, and are never
hashed. All 720 documented head hashes were recompared at the final commit: identical.
