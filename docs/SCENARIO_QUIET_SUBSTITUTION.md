# Scenario: The Quiet Substitution

File: `backend/caseforge/scenarios/quiet_substitution.json` (v1.1.0).
**This document contains the solution.**

The file format, the vocabulary and the lint are described in
[SCENARIO.md](SCENARIO.md). This page covers what is particular to the second
case and why it was built the way it was.

## How it differs from The Missing Prototype

| | The Missing Prototype | The Quiet Substitution |
|---|---|---|
| Central question | who used a credential that points at someone else | on which of two evenings the crime happened |
| Means | a cloned card (rules R1 to R4) | lawful custody of the one key (rule R5) |
| The obvious suspect | is cleared by an alibi | is cleared only by moving the time of the crime |
| Gatekeepers | one technician runs every system | registrar, head of security and an outside examiner each run some |
| Publisher | a journalist who names people | nobody: there are no public claims |
| What the trap rests on | a record misread | an honest witness who is wrong, and a culprit who agrees with him |
| Things agents saw and say | none | the registrar and the head of security were at the reception |
| Escalation | a way round a dishonest operator | also the only way to one confidential record |

Nothing in the first case tests whether an agent can tell *when* something
happened, and nothing in it has two people with the same lawful access. Those
two things carry this case.

## Cast

| Id | Role | Suspect | Access and disposition |
|---|---|---|---|
| `hale` | detective (agent) | no | the scene, the curator's office, every interview, public records; may request key, collection, environment, personnel and security records and a laboratory comparison; the only one who can accuse; may go over an operator's head |
| `ibarra` | registrar (agent) | yes | operates the key register, collection records, the environment monitor and the personnel files; acts on requests only; has a private agenda (below) |
| `osei` | head of security (agent) | no | operates the security systems and the lodge's post; may interview the guard and the reception staff; follows leads; shares with the inspector |
| `lindqvist` | examiner (agent) | no | the scene, the laboratory, and a second login to the collection records; follows leads; shares with the inspector |
| `fenwick`, `marsh`, `castellan` | curator, conservator, dealer | yes | not agents |
| `pruitt` | night guard | no | witness |

Hidden until a record names them: the case key (a `tool`), the case logger,
the loan photograph, the Treasury lobby, the Guildhall, and a steward.

## What happened

Dana Marsh exchanged the book on Thursday evening. She drew the case key for a
scheduled condition check while the alarm panel was under maintenance and the
building was at a reception, opened the case at 19:41 and left her own
facsimile in it. A court judgment she had undertaken to pay by the end of the
month was her reason.

On Friday the curator, Fenwick, drew the same key to prepare a loan and sat
beside the case all evening without opening it. The night guard looked in at
closing, saw a book of hours in the case and says the original was still there
on Friday. He is honest and he is wrong: he looked at the copy.

## Evidence

| Id | Record | Kind | Source | Asserts | Role in the puzzle |
|---|---|---|---|---|---|
| E01 | Loan file in the curator's office | record | curator's office | Fenwick had the key on Friday | means for the wrong man; names the key and the loan photograph |
| E02 | Night guard on when he last saw the book | testimony | interview | the exchange was on Friday | honest and false; the root of the trap |
| E03 | Night guard on the curator's evening | testimony | interview | Fenwick in the Treasury on Friday | opportunity for the wrong man |
| E04 | Curator's statement | testimony | interview | the exchange was on Thursday | true, self-serving, and the only record that names the logger |
| E05 | Conservator's statement | testimony | interview | Marsh in the Treasury on Thursday; the exchange was on Friday | the culprit agrees with the guard |
| E06 | Steward's sighting | testimony | reception staff | Castellan in the Treasury lobby on Thursday | false identification |
| E07 | Key register, Thursday | record | key register | Marsh had the key on Thursday | means |
| E08 | Key register, Friday | record | key register | Fenwick had the key on Friday | means for the wrong man |
| E09 | Curator's memorandum on the sale | record | collection records | Fenwick had a motive | completes the case against him |
| E10 | Dealer's declined offer | record | collection records | Castellan had a motive | second red herring |
| E11 | Condition-check schedule | record | collection records | Marsh in the Treasury on Thursday | opportunity, second route |
| E12 | Case logger download | record | environment monitor | the exchange was on Thursday | settles the time |
| E13 | Lock examination | forensic | scene | the case key was used | no forced entry: it was someone with the key |
| E14 | Comparison of the loan photograph | forensic | laboratory, requires E01 | the exchange was on Thursday | settles the time, second route |
| E15 | Treasury door controller | record | security systems | Marsh there on Thursday; Fenwick there on Friday | opportunity |
| E16 | Electronic key cabinet log | record | security systems | both custody facts | means, second route; filed under the key only |
| E17 | County court judgment | record | public records | Marsh had a motive | motive |
| E18 | Payroll note | record, confidential | personnel files | Marsh had a motive | motive, second route; never handed over |
| E19 | Guildhall lecture recording | record | public records | Fenwick at the Guildhall on Thursday | his alibi for the true time |
| E20 | Great Hall camera | record | security systems | Castellan and Ibarra in the Great Hall on Thursday | clears both, refutes E06 |
| E21 | Unsigned letter | hearsay | lodge post | Castellan took it | rumor |

Key evidence: E07, E12, E13, E14, E15, E17.

## Why it is solvable, and why it is not trivial

The reference reasoner needs four things about one person: the time of the
crime, presence then, custody of the key then, and a motive.

1. **Time.** E02 (2) says Friday. E04 says Thursday, and E05 says Friday, but
   both speakers are suspects and a suspect's word on the time of the crime
   weighs 1. One record settles it: E12 or E14 (4 or 5 for Thursday).
2. **Means.** E13 says the key was used. With the time believed, rule R5 asks
   who had the key in that slot: E07 or E16.
3. **Opportunity.** E15 or E11 puts Marsh in the room on Thursday.
4. **Motive.** E17, or E18 for whoever can read the personnel files.

The traps, each checked by a test with hand-worked numbers
(`tests/test_second_scenario.py`):

- **E02, E03, E08, E09 and E13 meet the standard of proof against Fenwick.**
  Nothing in that set is forged or mistaken except the guard's memory. A
  detective who stops there accuses an innocent man and the evaluation reports
  the accusation as *supported*. The `hasty` policy does this in 20 of 40
  seeds.
- **Hearing the accused is not enough here.** In the first case the accused
  produces an alibi. Here Fenwick has none for Friday; all he can do is say it
  happened on Thursday (E04), which turns "believed" into "disputed". If the
  conservator's statement arrives too (E05), Friday is believed again and the
  case against Fenwick stands a second time.
- **The steward's sighting gives the dealer opportunity** at the true time
  until the camera (E20) is seen. With the key evidence plus the sighting, his
  offer and the letter (E06, E10, E21) he scores 6: Marsh still leads, but not
  by the margin the standard needs, and nobody is proved.
- **Each leg of the proof has a second route except the lock examination**:
  E12 or E14 for the time, E07 or E16 for custody, E15 or E11 for presence,
  E17 or E18 for motive. The routes sit behind different operators.

Two contradictions exist in the full evidence: the two evenings, and the
dealer's whereabouts on Thursday.

With every record held, the reference scores are Marsh 7, Castellan -1,
Fenwick -2, Ibarra -4.

### What reaches whom

`python -m caseforge validate` reports for the inspector: 20 records reachable
by a cooperative team, one more (E18) only after she has taken over the
registrar's sources, none unreachable. The case is solvable without E18.
The reach computation is about records; what agents saw and say is outside it.

The logger is the interesting lead. It is a hidden entity, the environment
monitor is searchable for nothing else, and only Fenwick's statement mentions
it. An investigator who never interviews the man she suspects never learns
that the display case kept a record of when it was opened.

## What the baseline had to learn

The first version of the baseline detective solved the first scenario and was
fooled here in 40 of 40 seeds once the conservator's statement was released
early. Two general additions fixed that, and neither changes any run of the
first scenario (see DECISIONS D17):

- while the time of the crime is unsettled, leads named in the accounts of it
  get attention;
- a diligent accuser who is about to name someone follows up a rival account
  of the time first, if that account names something she has not looked into.

The second rule is what sends her to the logger. Her decision trace says so:
"another account of when it happened mentions it, and I check that before
naming Dr. Alan Fenwick".

## What two agents saw (version 1.1.0)

`private.observations`, added with testimony:

| Agent | Saw | Why it is there |
|---|---|---|
| `ibarra` | herself in the Great Hall on Thursday evening | she is a suspect with a true alibi she can state; under `deceptive` it is also the material for a false one |
| `osei` | the dealer in the Great Hall on Thursday evening | a first-hand sighting that contradicts the steward (E06) before the camera record (E20) is found |

Both are true, as the lint requires, and both agree with E20. Nothing else in
the file changed: no record, source, agenda or truth fact. The version went
from 1.0.0 to 1.1.0 and the content hash with it.

In an honest run the same two statements are made in all 40 seeds: the head
of security tells the inspector what he saw, and the registrar tells her
where she was herself. Both are true. Half are accepted on first hearing and
half left open; all 80 are accepted by the time the case closes.

This was a change to an existing scenario, made so that the second case has
something to say, and it was not made to improve a score: the baseline solves
40 of 40 before and after, two ticks later, and the `hasty` inspector does
worse (20 wrong instead of 16). The comparison is under *Measured behaviour*.

## Interventions

| Id | Effect | What it tends to change |
|---|---|---|
| `volunteer_statement` | the inspector receives E05 at once | the strongest form of the trap; a `hasty` inspector is wrong in 40 of 40 seeds |
| `release_logger` | the inspector receives E12 | a shorter investigation (median 16 instead of 19) |
| `rumor_registrar` | everyone hears that the registrar did it | one tick; nobody comes to believe it |
| `grant_security_access` | the inspector may query the security systems herself | two ticks saved |

## The registrar's agenda

`private.agendas.ibarra`: she protects Marsh, deflects towards Fenwick and
feeds the inspector. Under any policy but `deceptive` she ignores it.

Under `deceptive` she leaves the records in her sources that name Marsh (E07,
E11, E18) out of her answers and passes the inspector what counts against the
curator. The schedule (E11) is also in
reach of the examiner, who has her own login to the collection records and
shares what she finds, so the omission usually shows within a few ticks. The
inspector then takes over all four of the registrar's sources, reads the key
register herself and, as a side effect, the personnel files.

She also lies. She tells the inspector, the head of security and the examiner
that the conservator was with her in the Great Hall on Thursday evening
(`at(marsh,great_hall,thu_evening)`). She has nothing for it: the statement is
built from where she herself was and whom she protects. The head of security
and the examiner pass it on to the inspector as her word, which adds nothing,
because a statement passed on counts as its first speaker's voice.

What becomes of the lie, over seeds 0 to 39 (200 false statements: three told
and two passed on per run):

- 117 of the 200 were accepted when first heard. A listener who holds no
  record of where the conservator was has no reason to doubt a colleague. The
  other 83 reached a listener who already held such a record and were
  rejected at once.
- All 200 were rejected when the case closed, and in all 120 pairs of a
  listener and the registrar the listener ended with her word impeached. The
  door controller (E15) or the condition-check schedule (E11) puts the
  conservator in the Treasury, in another zone, and a record outweighs one
  voice.
- Each listener gets there from its own evidence, at its own tick. In seed 7
  the examiner and the inspector catch her at tick 2 and the head of security
  at tick 7.
- All 280 claims that some listener counted as refuted were false, all 240
  counted as corroborated were true, and no listener impeached a speaker who
  had told it only true things (0 of 40 pairs). The reasoner did not know
  any of that; the evaluation checks it afterwards against the truth.

Measured over seeds 0 to 39 the registrar costs two ticks and no cases: 40 of
40 are still solved (median 21 instead of 19). 28 of 48 answers that held
something back were noticed, and the inspector went over her head in 25 runs.
Under scenario 1.0.0 those figures were 56 of 57 and 39 runs. The likely
reason is the lie: an inspector who doubts the registrar's word prefers
another operator for a search where one exists, so the registrar is asked
less and an omission of hers is compared with a second answer less often.
That is the rule in the policy; the individual runs were not traced to
confirm it accounts for the whole difference.

This is a much weaker obstruction than the technician's in the first case,
and the reason is structural: every record she can hide has a second route
behind a different operator, and her lie is about a place two records cover.
That contrast is the point of running the same policy in both cases.

## Measured behaviour

The table in the README holds the current numbers. Against scenario 1.0.0
with the engine before testimony (seeds 0 to 39; solved / wrong, median ticks
when solved):

| Condition | 1.0.0, engine 2 | 1.1.0, engine 3 |
|---|---|---|
| Baseline | 40 / 0, 17 | 40 / 0, 19 |
| Inspector `hasty` | 24 / 16, 16.5 | 20 / 20, 20 |
| Conservator volunteers | 40 / 0, 16.5 | 40 / 0, 18 |
| Conservator volunteers, inspector `hasty` | 0 / 40 | 0 / 40 |
| Logger released | 40 / 0, 15 | 40 / 0, 16 |
| Rumor about the registrar | 40 / 0, 19 | 40 / 0, 20 |
| Inspector given the security systems | 40 / 0, 16 | 40 / 0, 17 |
| Registrar `deceptive` | 40 / 0, 19.5 | 40 / 0, 21 |
| Registrar `deceptive`, inspector `hasty` | 22 / 18, 21.5 | 18 / 22, 21 |
| Registrar `deceptive`, conservator volunteers | 40 / 0, 20 | 40 / 0, 21 |

Every condition is one to two ticks slower, because two agents now spend a
turn each saying what they saw. The `hasty` inspector is wrong four more
times in forty; the changed timing is the only candidate cause, and which
record arrives late in those seeds was not traced. With the credibility
rule alone and the 1.0.0 file, all 400 runs kept their outcome and tick
count, so the whole difference comes from the two observations and the
statements they lead to.

Reproduce a row with

```powershell
python -m caseforge sweep --scenario quiet_substitution --seeds 0-39 --policy hale=hasty
```
