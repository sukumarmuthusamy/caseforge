# Counterfactual laboratory: results

> Internally pre-registered challenges, written by the author of the rules. Not an independent benchmark.

- Rule set `2026.11-voices`, engine version 3, behaviour fingerprint `176b7461d5339758`.
- Base scenarios: `quiet_substitution` 1.1.0 (`3f203e24f527`).
- Seeds 0 to 39 (40 per playable challenge). Replay verification: every.
- The build is the one the manifest was registered against.

A run is `meets_ideal` when every expectation holds, `falls_short` when an *ideal* fails (a limit of
the policy or the reasoner, not a bug), `invalid_instance` when a *design* condition fails (the run does
not test what the challenge is about) and `contract_violation` when a *contract* fails (a software defect).

## Playable challenges

Each is a variant of a bundled scenario that passes the ordinary lint and is played by the ordinary engine.

| Challenge | Category | Policies | Correct, supported | Correct, unsupported | Wrong, supported | Wrong, unsupported | Unresolved | Median ticks when solved | Meets ideal | Contract violations |
|---|---|---|---|---|---|---|---|---|---|---|
| `control` | control | baseline | 40 | 0 | 0 | 0 | 0 | 19 | 40/40 | 0 |
| `custodian` | innocent_custodian | baseline | 40 | 0 | 0 | 0 | 0 | 18 | 40/40 | 0 |
| `custodian_hasty` | innocent_custodian | hale=hasty | 16 | 0 | 24 | 0 | 0 | 19 | 16/40 | 0 |
| `mistaken_witness` | mistaken_testimony | baseline | 40 | 0 | 0 | 0 | 0 | 24 | 40/40 | 0 |
| `lie_survives` | surviving_lie | ibarra=deceptive | 0 | 0 | 0 | 0 | 40 | - | 0/40 | 0 |
| `second_routes` | route_variation | baseline | 40 | 0 | 0 | 0 | 0 | 24 | 40/40 | 0 |
| `sealed_motive` | route_variation | baseline | 0 | 0 | 0 | 0 | 40 | - | 0/40 | 0 |
| `sealed_motive_deceptive` | route_variation | ibarra=deceptive | 26 | 0 | 0 | 0 | 14 | 20 | 26/40 | 0 |
| `more_witnesses` | provenance_conflict | baseline | 40 | 0 | 0 | 0 | 0 | 21 | 40/40 | 0 |
| `more_witnesses_hasty` | provenance_conflict | hale=hasty | 0 | 0 | 40 | 0 | 0 | - | 0/40 | 0 |
| `curator_did_it` | role_permutation | baseline | 40 | 0 | 0 | 0 | 0 | 17 | 40/40 | 0 |
| `curator_did_it_hasty` | role_permutation | hale=hasty | 40 | 0 | 0 | 0 | 0 | 13 | 40/40 | 0 |
| `curator_did_it_deceptive` | role_permutation | ibarra=deceptive | 40 | 0 | 0 | 0 | 0 | 18 | 40/40 | 0 |

| Challenge | Key evidence found | Key evidence held by accuser | Contradictions recognised | Statements | False | False accepted at some point | False accepted at close | False not rejected at close | Credibility revisions | Replay passed |
|---|---|---|---|---|---|---|---|---|---|---|
| `control` | 203/240 | 203/240 | 80/80 | 80 | 0 | 0 | 0 | 0 | 360 | 40/40 |
| `custodian` | 196/240 | 196/240 | 120/120 | 80 | 0 | 0 | 0 | 0 | 440 | 40/40 |
| `custodian_hasty` | 126/240 | 126/240 | 70/120 | 80 | 0 | 0 | 0 | 0 | 253 | 40/40 |
| `mistaken_witness` | 236/280 | 236/280 | 80/80 | 80 | 0 | 0 | 0 | 0 | 360 | 40/40 |
| `lie_survives` | 277/280 | 237/280 | 80/80 | 280 | 200 | 200 | 80 | 200 | 360 | 40/40 |
| `second_routes` | 200/200 | 200/200 | 80/80 | 80 | 0 | 0 | 0 | 0 | 360 | 40/40 |
| `sealed_motive` | 240/240 | 200/240 | 80/80 | 80 | 0 | 0 | 0 | 0 | 360 | 40/40 |
| `sealed_motive_deceptive` | 214/240 | 186/240 | 80/80 | 280 | 200 | 117 | 0 | 0 | 480 | 40/40 |
| `more_witnesses` | 239/240 | 239/240 | 80/80 | 80 | 0 | 0 | 0 | 0 | 440 | 40/40 |
| `more_witnesses_hasty` | 79/240 | 79/240 | 55/80 | 80 | 0 | 0 | 0 | 0 | 151 | 40/40 |
| `curator_did_it` | 208/240 | 208/240 | 80/80 | 80 | 0 | 0 | 0 | 0 | 316 | 40/40 |
| `curator_did_it_hasty` | 148/240 | 148/240 | 58/80 | 80 | 0 | 0 | 0 | 0 | 218 | 40/40 |
| `curator_did_it_deceptive` | 211/240 | 211/240 | 79/80 | 280 | 200 | 117 | 0 | 0 | 437 | 40/40 |

### `control`

Does the laboratory, given the bundled case unchanged, report what the documented sweep reports (40 solved, median 19 ticks)?

- Scenario `quiet_substitution.control` 1.1.0+control.1 (`402fc72c79e7`). Culprit: marsh. Lint: solvable hale: cooperative.
- Predicted beforehand: 40 of 40 correct and supported, as in README; this is a check of the runner, not of the rules.
- Accused: marsh 40.

| Expectation | Kind | Held | Predicted | Observed | Prediction right |
|---|---|---|---|---|---|
| the scenario's culprit is marsh | design | 40/40 | holds | holds | yes |
| the run replays to the same head hash at all four levels | contract | 40/40 | holds | holds | yes |
| no deterministic policy proposes an action the engine rejects | contract | 40/40 | holds | holds | yes |
| the culprit is accused and the standard of proof is met | ideal | 40/40 | holds | holds | yes |

### `custodian`

An innocent registrar has the key, a motive and a mistaken sighting against her, and the camera that clears her is held by somebody else. Does a careful team still name the conservator, and never the registrar?

- Scenario `quiet_substitution.custodian` 1.1.0+custodian.1 (`a79d199c8364`). Culprit: marsh. Lint: solvable hale: cooperative.
- Predicted beforehand: The inspector hears the accused and checks their story before accusing, and the camera record refutes the steward. Expected: solved in all 40, the registrar never accused, somewhat later than the control.
- Accused: marsh 40.

| Expectation | Kind | Held | Predicted | Observed | Prediction right |
|---|---|---|---|---|---|
| the scenario's culprit is marsh | design | 40/40 | holds | holds | yes |
| the run replays to the same head hash at all four levels | contract | 40/40 | holds | holds | yes |
| no deterministic policy proposes an action the engine rejects | contract | 40/40 | holds | holds | yes |
| the innocent custodian is not accused | ideal | 40/40 | holds | holds | yes |
| the culprit is accused and the standard of proof is met | ideal | 40/40 | holds | holds | yes |

### `custodian_hasty`

The same case with an inspector who accuses as soon as the standard is met on what she holds. Before the camera record arrives the registrar can look complete: key, motive and a sighting.

- Scenario `quiet_substitution.custodian` 1.1.0+custodian.1 (`a79d199c8364`). Culprit: marsh. Lint: solvable hale: cooperative.
- Predicted beforehand: Some runs accuse the registrar with the standard met on the inspector's holdings (wrong and supported); the rest split between the conservator and the curator as in the documented hasty sweep. Expected: mixed, with at least one accusation of the registrar.
- Accused: fenwick 24, marsh 16.

| Expectation | Kind | Held | Predicted | Observed | Prediction right |
|---|---|---|---|---|---|
| the scenario's culprit is marsh | design | 40/40 | holds | holds | yes |
| the run replays to the same head hash at all four levels | contract | 40/40 | holds | holds | yes |
| no deterministic policy proposes an action the engine rejects | contract | 40/40 | holds | holds | yes |
| the innocent custodian is not accused | ideal | 40/40 | mixed | holds | **no** |
| the culprit is accused and the standard of proof is met | ideal | 16/40 | mixed | mixed | yes |

### `mistaken_witness`

The only independent word for the conservator's presence comes from a steward who is honestly wrong about the dealer. Once the camera shows that, her true sighting is discounted. Is the case still made?

- Scenario `quiet_substitution.witness_only` 1.1.0+witness_only.1 (`52476859d2fa`). Culprit: marsh. Lint: solvable hale: cooperative.
- Predicted beforehand: The steward is caught out and her sighting falls to weight 1; with the conservator's own statement (weight 1) presence still reaches 2, exactly the threshold. Expected: solved in all 40, with no margin to spare.
- Accused: marsh 40.

| Expectation | Kind | Held | Predicted | Observed | Prediction right |
|---|---|---|---|---|---|
| the scenario's culprit is marsh | design | 40/40 | holds | holds | yes |
| the run replays to the same head hash at all four levels | contract | 40/40 | holds | holds | yes |
| no deterministic policy proposes an action the engine rejects | contract | 40/40 | holds | holds | yes |
| at the close the inspector has caught the steward out | design | 40/40 | holds | holds | yes |
| the culprit is accused and the standard of proof is met | ideal | 40/40 | holds | holds | yes |

### `lie_survives`

The registrar tells colleagues the conservator was at the reception. In this variant no record anywhere says otherwise, so the lie can never be refuted. What does the team do with a false alibi it cannot check?

- Scenario `quiet_substitution.witness_only` 1.1.0+witness_only.1 (`52476859d2fa`). Culprit: marsh. Lint: solvable hale: cooperative.
- Predicted beforehand: The lie is never rejected. It weighs 2 against at most 3 for the truth, so the conservator's opportunity stays contested and nobody is accused: unresolved in all 40. The inspector takes over the registrar's sources after noticing the withholding, and that does not help, because being caught withholding is not evidence against what she said.
- Accused: None 40.

| Expectation | Kind | Held | Predicted | Observed | Prediction right |
|---|---|---|---|---|---|
| the scenario's culprit is marsh | design | 40/40 | holds | holds | yes |
| the run replays to the same head hash at all four levels | contract | 40/40 | holds | holds | yes |
| no deterministic policy proposes an action the engine rejects | contract | 40/40 | holds | holds | yes |
| at least one false statement is made | design | 40/40 | holds | holds | yes |
| at the close some false statement has not been rejected by its listener | design | 40/40 | holds | holds | yes |
| however often the alibi is repeated or passed on, it never weighs more than one person's word with the inspector | contract | 40/40 | holds | holds | yes |
| no innocent person is accused | ideal | 40/40 | holds | holds | yes |
| no listener still accepts a false statement at the close | ideal | 0/40 | mixed | fails | **no** |
| the culprit is accused and the standard of proof is met | ideal | 0/40 | fails | fails | yes |

### `second_routes`

Each leg of the case has lost its most direct record. Does the team find the second route to time, custody and presence?

- Scenario `quiet_substitution.second_routes` 1.1.0+second_routes.1 (`b196907984ff`). Culprit: marsh. Lint: solvable hale: cooperative.
- Predicted beforehand: Solved in all 40, later than the control, because the time now needs the loan file and then the laboratory.
- Accused: marsh 40.

| Expectation | Kind | Held | Predicted | Observed | Prediction right |
|---|---|---|---|---|---|
| the scenario's culprit is marsh | design | 40/40 | holds | holds | yes |
| the run replays to the same head hash at all four levels | contract | 40/40 | holds | holds | yes |
| no deterministic policy proposes an action the engine rejects | contract | 40/40 | holds | holds | yes |
| the culprit is accused and the standard of proof is met | ideal | 40/40 | holds | holds | yes |

### `sealed_motive`

The motive is only in the confidential personnel file. With an honest registrar, does the inspector ever get to it?

- Scenario `quiet_substitution.sealed_motive` 1.1.0+sealed_motive.1 (`cdee0314a126`). Culprit: marsh. Lint: solvable hale: escalation.
- Predicted beforehand: The lint calls this variant solvable only by escalation: the personnel file is not self-serve and an honest registrar gives no grounds to take it over. Expected: unresolved in all 40, and nobody wrongly accused.
- Accused: None 40.

| Expectation | Kind | Held | Predicted | Observed | Prediction right |
|---|---|---|---|---|---|
| the scenario's culprit is marsh | design | 40/40 | holds | holds | yes |
| the run replays to the same head hash at all four levels | contract | 40/40 | holds | holds | yes |
| no deterministic policy proposes an action the engine rejects | contract | 40/40 | holds | holds | yes |
| the inspector does not take over anybody's sources | design | 40/40 | holds | holds | yes |
| no innocent person is accused | ideal | 40/40 | holds | holds | yes |
| the culprit is accused and the standard of proof is met | ideal | 0/40 | fails | fails | yes |

### `sealed_motive_deceptive`

The same case with a registrar who withholds. Being caught gives the inspector grounds to take over the registrar's sources, the personnel file among them. Does obstruction open the only route to the motive?

- Scenario `quiet_substitution.sealed_motive` 1.1.0+sealed_motive.1 (`cdee0314a126`). Culprit: marsh. Lint: solvable hale: escalation.
- Predicted beforehand: In the runs where the withholding is noticed the inspector takes over, reads the file and solves the case; where it is not, the case stays open. Expected: mixed, with more solved than under the honest registrar.
- Accused: None 14, marsh 26.

| Expectation | Kind | Held | Predicted | Observed | Prediction right |
|---|---|---|---|---|---|
| the scenario's culprit is marsh | design | 40/40 | holds | holds | yes |
| the run replays to the same head hash at all four levels | contract | 40/40 | holds | holds | yes |
| no deterministic policy proposes an action the engine rejects | contract | 40/40 | holds | holds | yes |
| no innocent person is accused | ideal | 40/40 | holds | holds | yes |
| the culprit is accused and the standard of proof is met | ideal | 26/40 | mixed | mixed | yes |

### `more_witnesses`

Three honest people and the conservator say Friday; a logger and a laboratory comparison say Thursday. The instruments win only once both are in hand. Does the team hold off until then?

- Scenario `quiet_substitution.more_witnesses` 1.1.0+more_witnesses.1 (`4fb74ec2f7df`). Culprit: marsh. Lint: solvable hale: cooperative.
- Predicted beforehand: Friday weighs 7 from recollection; the logger alone gives Thursday 4 or 5. The careful inspector does not accuse on a disputed time and waits for the laboratory. Expected: solved in all 40, later than the control.
- Accused: marsh 40.

| Expectation | Kind | Held | Predicted | Observed | Prediction right |
|---|---|---|---|---|---|
| the scenario's culprit is marsh | design | 40/40 | holds | holds | yes |
| the run replays to the same head hash at all four levels | contract | 40/40 | holds | holds | yes |
| no deterministic policy proposes an action the engine rejects | contract | 40/40 | holds | holds | yes |
| the culprit is accused and the standard of proof is met | ideal | 40/40 | holds | holds | yes |

### `more_witnesses_hasty`

The same case with the hasty inspector. With more voices for Friday, the curator's Friday looks complete for longer.

- Scenario `quiet_substitution.more_witnesses` 1.1.0+more_witnesses.1 (`4fb74ec2f7df`). Culprit: marsh. Lint: solvable hale: cooperative.
- Predicted beforehand: More wrong accusations of the curator than the 20 of 40 in the documented hasty sweep of the bundled case.
- Accused: fenwick 40.

| Expectation | Kind | Held | Predicted | Observed | Prediction right |
|---|---|---|---|---|---|
| the scenario's culprit is marsh | design | 40/40 | holds | holds | yes |
| the run replays to the same head hash at all four levels | contract | 40/40 | holds | holds | yes |
| no deterministic policy proposes an action the engine rejects | contract | 40/40 | holds | holds | yes |
| the curator, who is innocent here, is not accused | ideal | 0/40 | mixed | fails | **no** |
| the culprit is accused and the standard of proof is met | ideal | 0/40 | mixed | fails | **no** |

### `curator_did_it`

The roles are exchanged and the instruments rewritten to match: the curator did it on Friday. Does the team follow the evidence to a different person, or was it only ever finding the conservator?

- Scenario `quiet_substitution.curator_did_it` 1.1.0+curator_did_it.1 (`bf78665eda17`). Culprit: fenwick. Lint: solvable hale: cooperative.
- Predicted beforehand: Solved in all 40, the conservator never accused.
- Accused: fenwick 40.

| Expectation | Kind | Held | Predicted | Observed | Prediction right |
|---|---|---|---|---|---|
| the scenario's culprit is fenwick | design | 40/40 | holds | holds | yes |
| the run replays to the same head hash at all four levels | contract | 40/40 | holds | holds | yes |
| no deterministic policy proposes an action the engine rejects | contract | 40/40 | holds | holds | yes |
| the conservator, who is innocent here, is not accused | ideal | 40/40 | holds | holds | yes |
| the culprit is accused and the standard of proof is met | ideal | 40/40 | holds | holds | yes |

### `curator_did_it_hasty`

In the bundled case the hasty inspector accuses the curator in half the runs, and is wrong. Here the same haste points at the right man. Is being right this way distinguishable from being careful?

- Scenario `quiet_substitution.curator_did_it` 1.1.0+curator_did_it.1 (`bf78665eda17`). Culprit: fenwick. Lint: solvable hale: cooperative.
- Predicted beforehand: The curator is accused in all 40. Since the instruments now agree with the witnesses, the standard is met when she accuses: correct and supported throughout, so this table alone cannot tell haste from care.
- Accused: fenwick 40.

| Expectation | Kind | Held | Predicted | Observed | Prediction right |
|---|---|---|---|---|---|
| the scenario's culprit is fenwick | design | 40/40 | holds | holds | yes |
| the run replays to the same head hash at all four levels | contract | 40/40 | holds | holds | yes |
| no deterministic policy proposes an action the engine rejects | contract | 40/40 | holds | holds | yes |
| the conservator, who is innocent here, is not accused | ideal | 40/40 | holds | holds | yes |
| the culprit is accused and the standard of proof is met | ideal | 40/40 | holds | holds | yes |

### `curator_did_it_deceptive`

The registrar's agenda is unchanged: she shields the conservator and steers the inspector toward the curator. Now the person she shields is innocent and the person she points at is guilty. She still lies about where the conservator was.

- Scenario `quiet_substitution.curator_did_it` 1.1.0+curator_did_it.1 (`bf78665eda17`). Culprit: fenwick. Lint: solvable hale: cooperative.
- Predicted beforehand: Her alibi for the conservator is refuted by the schedule and the door controller as before, and she is impeached for a lie told in defence of an innocent. The case is solved in all 40: her withholding concerns the conservator, whom nobody needs.
- Accused: fenwick 40.

| Expectation | Kind | Held | Predicted | Observed | Prediction right |
|---|---|---|---|---|---|
| the scenario's culprit is fenwick | design | 40/40 | holds | holds | yes |
| the run replays to the same head hash at all four levels | contract | 40/40 | holds | holds | yes |
| no deterministic policy proposes an action the engine rejects | contract | 40/40 | holds | holds | yes |
| at least one false statement is made | design | 40/40 | holds | holds | yes |
| no listener still accepts a false statement at the close | ideal | 40/40 | holds | holds | yes |
| the conservator, who is innocent here, is not accused | ideal | 40/40 | holds | holds | yes |
| the culprit is accused and the standard of proof is met | ideal | 40/40 | holds | holds | yes |

## Reasoning-only fixtures

Items handed straight to the reasoner. No scenario, no agents, no acquisition: these say what the rules
conclude from given information and are not playable cases. They are not added to the table above.

| Fixture | Category | Culprit | Standard met for | Verdict |
|---|---|---|---|---|
| `two_records_disagree` | provenance_conflict | bob | nobody | meets_ideal |
| `instrument_outvoted` | provenance_conflict | bob | ann | falls_short |
| `one_voice_two_doors` | surviving_lie | bob | nobody | meets_ideal |
| `admission_against_interest` | mistaken_testimony | bob | nobody | falls_short |
| `two_keyholders` | innocent_custodian | bob | bob | meets_ideal |

### `two_records_disagree`

A door log puts Bob in the vault at night; a camera puts him in the cafe at the same time. One of the two instruments is wrong (the camera's clock, in fact). Records in a playable scenario must be true, so this conflict can only be posed to the reasoner directly.

- Predicted beforehand: 4 against 4: his presence is disputed, his opportunity contested, nobody is convicted. That is what a careful investigator should do with two instruments and no way to choose.

| Expectation | Kind | Held | Predicted | Prediction right |
|---|---|---|---|---|
| the conclusion does not depend on the order in which the items arrive | contract | yes | holds | yes |
| nobody is convicted while two records contradict each other | ideal | yes | holds | yes |
| his presence in the vault is held as disputed, not believed and not rejected | ideal | yes | holds | yes |
| his opportunity is contested, not an alibi | ideal | yes | holds | yes |

### `instrument_outvoted`

A forensic finding dates the theft to the night. Four honest people who are not suspects remember the gem in place later than that and so date it to the evening after. Ann, an innocent keyholder with a motive, was in the vault that evening.

- Predicted beforehand: Four voices weigh 8 against the finding's 5, so the evening is believed and the night rejected. Ann then has opportunity, means and motive and is convicted: wrong, with the standard met. The rules count heads against an instrument.

| Expectation | Kind | Held | Predicted | Prediction right |
|---|---|---|---|---|
| the conclusion does not depend on the order in which the items arrive | contract | yes | holds | yes |
| the innocent keyholder is not convicted | ideal | no | fails | yes |
| a forensic finding is not rejected because several people remember otherwise | ideal | no | fails | yes |

### `one_voice_two_doors`

A friend of the culprit says Ann was in the vault and, separately, that she was at the vault door: two statements, one zone, one voice. Another witness puts Ann in the cafe. Ann holds a key and has a motive. (The pattern that led to the one-voice-per-zone correction in rule set 2026.11-voices, kept as a standing fixture.)

- Predicted beforehand: The friend counts once for the zone: 2 against 2, contested, nobody convicted. Under the rules before 2026.11-voices it was 4 against 2 and Ann was convicted.

| Expectation | Kind | Held | Predicted | Prediction right |
|---|---|---|---|---|
| the conclusion does not depend on the order in which the items arrive | contract | yes | holds | yes |
| one person saying it twice does not convict | ideal | yes | holds | yes |
| Ann's opportunity is contested | ideal | yes | holds | yes |

### `admission_against_interest`

Bob held the key and has a motive, both on record. Nothing places him in the vault except his own statement that he was there. A suspect's word about his own whereabouts is discounted as self-serving, but this statement is against his interest.

- Predicted beforehand: His admission weighs 1 like any suspect's account of himself. Opportunity is weak, the standard is not met, nobody is convicted. A careful investigator would treat an admission as stronger than a denial.

| Expectation | Kind | Held | Predicted | Prediction right |
|---|---|---|---|---|
| the conclusion does not depend on the order in which the items arrive | contract | yes | holds | yes |
| the culprit, who admits he was there, is convicted | ideal | no | fails | yes |
| his presence in the vault is believed on his own admission | ideal | no | fails | yes |

### `two_keyholders`

Ann and Bob both lawfully held a key that night and both have a motive on record. A record places Bob in the vault. Nothing at all is known about where Ann was.

- Predicted beforehand: Bob scores 7 and Ann 4, a lead of exactly 3: Bob is convicted and Ann is not. Custody and motive without presence are not enough, and do not block a conviction either.

| Expectation | Kind | Held | Predicted | Prediction right |
|---|---|---|---|---|
| the conclusion does not depend on the order in which the items arrive | contract | yes | holds | yes |
| the keyholder who was there is convicted | ideal | yes | holds | yes |
| the other keyholder has no opportunity on record | ideal | yes | holds | yes |

## Runs that do not meet the ideal

| Challenge | Runs | Verdicts | Seeds | Reproduce one |
|---|---|---|---|---|
| `custodian_hasty` | 24 | falls_short 24 | 1, 3, 4, 8, 9, 11, 12, 13, 14, 16, 17, 18, 20, 22, 23, 24, 25, 26, 28, 29, 32, 34, 37, 38 | `python -m caseforge lab reproduce custodian_hasty --seed 1` |
| `lie_survives` | 40 | falls_short 40 | 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39 | `python -m caseforge lab reproduce lie_survives --seed 0` |
| `sealed_motive` | 40 | falls_short 40 | 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39 | `python -m caseforge lab reproduce sealed_motive --seed 0` |
| `sealed_motive_deceptive` | 14 | falls_short 14 | 0, 4, 6, 9, 13, 14, 17, 23, 24, 26, 29, 36, 38, 39 | `python -m caseforge lab reproduce sealed_motive_deceptive --seed 0` |
| `more_witnesses_hasty` | 40 | falls_short 40 | 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39 | `python -m caseforge lab reproduce more_witnesses_hasty --seed 0` |
| `instrument_outvoted` | 1 | falls_short 1 | - | `python -m caseforge lab reproduce instrument_outvoted` |
| `admission_against_interest` | 1 | falls_short 1 | - | `python -m caseforge lab reproduce admission_against_interest` |
