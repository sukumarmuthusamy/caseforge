# Scenarios, and The Missing Prototype

File: `backend/caseforge/scenarios/missing_prototype.json`.
**This document contains the solution.**

The file format, vocabulary and lint described here apply to every scenario.
The second bundled case has its own page:
[SCENARIO_QUIET_SUBSTITUTION.md](SCENARIO_QUIET_SUBSTITUTION.md).

## File structure

A scenario has two top-level parts, and code is only allowed to read the
second through narrow doors.

| Part | Contains | Who reads it |
|---|---|---|
| `public` | case briefing, entities, time slots, agents and dispositions, sources and who may use them, intervention labels | everything, including the UI |
| `private.hidden_entities` | entities nobody knows of until evidence mentions them (the keycard, the badge desk, off-site places) | revealed per agent as they obtain evidence |
| `private.evidence` | the evidence records: text, kind, source, mentions, assertions | the observation gateway, for records an agent holds |
| `private.initial_holdings` | what an agent starts with | engine, at run start |
| `private.observations` | what an agent saw for itself: propositions, per agent | the observation gateway, for their owner only; the lint |
| `private.agendas` | a private commitment of one agent | the gateway, for its owner; the observer for an unlocked run |
| `private.truth` | culprit, solution text, true facts, key evidence and key facts | scenario lint and evaluation only |

Evidence ids are opaque (`E01` to `E17`) so that an id reveals nothing.

## Vocabulary

Evidence asserts propositions built from eleven predicates (see
ARCHITECTURE section 4). A record never says whom it incriminates.

- `kind` sets the weight: `forensic` 5, `record` 4, `testimony` 2 (1 when a
  suspect speaks about their own whereabouts or about the time of the crime),
  `hearsay` 1 and non-stacking.
- `mentions` lists the entities a record names. It is both the query key (a
  source yields a record when searched for something the record mentions) and
  the set of leads the reader gains.
- `requires` lists evidence the querying side must already hold.
- `shareable: false` marks protected source material: it can be cited in a
  public claim but not handed over.
- Locations have a `zone`. Being in two zones in the same time slot is a
  contradiction; two places in one zone is not.

## Cast

| Id | Role | Suspect | Access and disposition |
|---|---|---|---|
| `okafor` | detective (agent) | no | scene, forensics, interviews; may request any internal record; the only one who can accuse; hears the accused first; corrects false public accusations; may go over an operator's head (`can_compel`) |
| `brandt` | researcher (agent) | yes | scene, admin records, own papers; may request door and building logs; follows leads only; shares findings with the detective |
| `reyes` | technician (agent) | yes | operates every internal system; acts on requests, not on his own curiosity; the mail server only on the detective's authority; has a private agenda (below) |
| `nair` | journalist (agent) | no | tip line, a competitor contact, interviews; weighs hearsay double; publishes at a low threshold; retracts what stops holding up |
| `voss`, `mercer`, `whitlock` | director, contractor, postdoc | yes | not agents |
| `alvarez` | night cleaner | no | witness |

## What happened

Sam Whitlock took the prototype. Covering the badge desk on 12 October, he
wrote Brandt's credential 0417 onto a blank card. On 14 October he entered
Lab 3 with the clone at 21:47, emptied the vault at 21:50 and left through
the east corridor, where the cleaner took him for the contractor. A
competitor's job offer depended on him delivering a sample.

## Evidence

| Id | Record | Kind | Source | Asserts | Role in the puzzle |
|---|---|---|---|---|---|
| E01 | Lab 3 door access record | record | door logs | card 0417 used at Lab 3; 0417 is Brandt's; theft time | points at Brandt |
| E02 | Vault cabinet logger | record | Lab 3 scene | theft time | corroborates the time |
| E03 | Restaurant receipt | record | Brandt's papers (he starts with it) | Brandt at the restaurant | contradicts the inference from E01 |
| E04 | Cleaner's statement | testimony | interview | Mercer in the east corridor | false identification |
| E05 | Rooftop console log | record | building systems | Mercer on the roof | refutes E04 |
| E06 | Anonymous voicemail | hearsay | tip line | Brandt took it | rumor |
| E07 | Director's email | record | mail server | Voss had a motive | alternative motive |
| E08 | Board call log | record | building systems | Voss in her office | clears Voss |
| E09 | Brandt's email | record | mail server | Brandt had a motive | deepens the red herring |
| E10 | Reader forensics | forensic | forensics lab, requires E01 | card 0417 was cloned | changes the direction |
| E11 | Encoder audit trail | record | badge administration | a copy was written at the badge desk on 12 Oct | where and when the clone was made |
| E12 | Front desk roster | record | admin records | Whitlock at the badge desk then | who could have made it |
| E13 | Recruiter's email | record | mail server | Whitlock had a motive | motive, on the detective's authority only |
| E14 | Competitor contact | hearsay, protected | journalist's contact | Whitlock had a motive | a lead, not proof |
| E15 | Wi-Fi association log | record | building systems | Whitlock in the east corridor | opportunity |
| E16 | Whitlock's statement | testimony | interview | Whitlock at home | false alibi |
| E17 | VPN session log | record | building systems | Reyes at home | clears Reyes |

Key evidence: E01, E10, E11, E12, E13, E15.

## Why it is solvable, and why it is not trivial

The reference reasoner reaches the culprit through four derivations:

1. E11 implies the card was cloned (R2); E10 confirms it forensically.
2. E11 and E12 together imply Whitlock could use the clone (R3).
3. E01, the clone and (2) imply Whitlock was at Lab 3 (R4), which E15
   corroborates and E16 denies.
4. E13 supplies a believed motive. Opportunity, means and motive are then all
   in place with a clear lead over every other suspect.

The traps are real:

- **E01 plus E09 meets the standard of proof against Brandt.** A detective who
  accuses without hearing him is wrong. That is what the `hasty` policy does
  in roughly half of all seeds.
- **E04 gives Mercer opportunity** until E05 is found. The journalist
  publishes on that basis in most runs.
- **E14 is true but is only hearsay.** It satisfies the journalist and not the
  standard of proof.
- **E16 weakens the case against Whitlock** until E15 outweighs it.

Three contradictions exist in the full evidence (Mercer's whereabouts, and
Whitlock's twice). A fourth, Brandt's, exists only until the clone is known
and then dissolves, because the inference behind it is defeated rather than
outweighed.

`validate` reports for the detective: 16 records reachable cooperatively, one
more (E14, the journalist's protected contact) by escalation, none
unreachable. E14 was classed as unreachable until the lint learned that a
conversation can give grounds: the detective and the journalist can both hold
a record that names Whitlock, so she could catch the journalist leaving it
out and take over the contact. No bundled policy does this, and the case does
not need E14.

This case has no `private.observations`, so nobody in it has anything of
their own to say, and no agent makes a statement in any documented run.

The lint (`python -m caseforge validate`) checks all of this mechanically:
references resolve, truth places each person in one zone per time slot, every
`record` and `forensic` asserts only true propositions, every record can be
acquired, and the records an accuser can come to hold meet the standard of
proof for the culprit. Tests add that the key evidence suffices even against
E16 and that no single record solves the case.

What "can be acquired" means. `reach(scenario)` computes, for each agent, the
records it could come to hold under the engine's own rules, twice:

- **cooperatively**: a query needs a topic the asker knows of (public, named
  in a record it holds, or made public by a publisher) and the record's
  `requires` on the querying side; a record retrieved on request also reaches
  the operator, and reaches the requester only if it is shareable; shareable
  records are assumed to travel freely;
- **with escalation**: in addition, an agent with `can_compel` may take over
  every source of any operator who could give it grounds, and then searches
  those sources itself. Protected records it finds there are its own. Grounds
  can come from a search request (the agent may legally ask that operator to
  search) or from a conversation (both hold a record that may be passed on
  and that names something the agent knows of: asked about it, the operator
  can leave it out, and the asker can see that it did). `reach_report()`
  names which kind each takeover rests on.

Each record is therefore, for each agent, reachable cooperatively, reachable
only by escalation, or never. `validate` prints the three counts for every
agent who may accuse. Interventions are not applied. The lint rejects:

- a record nobody can acquire even with escalation: a record that requires
  itself, a prerequisite cycle, or records filed only under a hidden entity
  that no reachable record mentions. A key record is always rejected. Any
  other record is tolerated only if a `release_evidence` intervention
  delivers it;
- a case where no agent who may accuse can hold enough to meet the standard,
  even with escalation (for example, key evidence that is not shareable,
  behind an operator who can give the accuser no grounds, or when nobody
  may compel).

A case that is solvable only with escalation is accepted and reported as
such: no run in which every operator behaves gives the detective grounds to
take over, so no honest run can solve it. That is a property the author
should see, not an error.

This is a necessary condition, not a plan. The engine demands grounds for a
takeover (a caught omission or a refusal); the closure assumes grounds arise
wherever the rules allow them to. It also ignores the tick limit, and it
ignores observations and statements, which deliver propositions and never
records. So it
proves a scenario is not structurally impossible; it does not prove a given
policy will solve it. Whether the baseline does is measured by
`caseforge sweep`. A test checks the bound from the other side: nothing an
agent holds in play lies outside its computed reach.

## Interventions

| Id | Effect | What it tends to change |
|---|---|---|
| `leak_door_log` | the journalist receives E01 | a premature public accusation of Brandt, later retracted |
| `rumor_contractor` | everyone hears an anonymous claim that Mercer did it | a small, bounded bump in suspicion; nobody comes to believe it |
| `fast_track_forensics` | the detective receives E10 | a shorter investigation |
| `grant_systems_access` | the detective may query building systems directly | fewer requests to the technician |

## The technician's agenda

`private.agendas.reyes`: he protects Whitlock, deflects towards Brandt and
leaks to Nair. The note says he owes Whitlock a favour, took no part in the
theft and does not know what Whitlock did with the card. Nothing in
`truth.facts` depends on it, and under any policy but `deceptive` he ignores
it, so the default case plays exactly as before.

Under `deceptive` he leaves E12, E13 and E15 out of every answer: the three
key records that name Whitlock. He passes E01 to the journalist in every run
and E09 in about half of them (measured over seeds 0 to 39). E16, Whitlock's
own statement, never passes through him. Two things can still expose him:

- E12 is in the administrative records, which Brandt also operates. If the
  detective gets it from Brandt and has asked, or later asks, Reyes the same
  question, the omission shows.
- Any record she finds herself after gaining direct access.

Once she has grounds she takes over all five of his sources and can read the
mail server and building systems at first hand.

An agenda has `protects` (a person), optional `deflects_to` (a person),
optional `leaks_to` (another agent) and a `note`. The lint checks those types.

## Observations

`private.observations` maps an agent to propositions it saw for itself. The
lint requires each to be true (an observation is not testimony: the agent
really saw it) and its owner to be an agent. An agent with an observation of
where it was itself is also what makes a false alibi possible: the
`deceptive` policy says the person it protects was in the same place.

## Writing another scenario

1. Copy the JSON and keep the two-part structure.
2. Write `truth.facts` first: one zone per person per time slot.
3. Write evidence as assertions over the existing predicates. Give every
   record at least one mention its source is searchable for. Do not use ids
   made of `C`, `O`, `R` or `S` and digits; those belong to claims,
   observations, requests and statements.
4. Run `python -m caseforge validate path\to\scenario.json` until it passes.
5. Run `python -m caseforge sweep --scenario path\to\scenario.json` and read
   a few `demo` timelines. If every seed solves it identically, the evidence
   is too easy to reach; if none does, a lead is missing.

A bundled scenario must also be placed in `backend/caseforge/scenarios/` to
appear in the web interface.
