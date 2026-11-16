"""Command line entry point: `python -m caseforge <command>`."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter

from .engine import Engine, EngineError, verify_run
from . import lab
from .evaluation import evaluate, summary_row
from .narrate import describe_proposition, narrate
from .scenario import Scenario, bundled_scenario_ids, lint, load_bundled, load_scenario_file, reach_report

DEFAULT_SCENARIO = "missing_prototype"


def _load(name: str) -> Scenario:
    return load_scenario_file(name) if name.endswith(".json") else load_bundled(name)


def _parse_policies(pairs: list[str]) -> dict[str, str]:
    policies = {}
    for pair in pairs:
        agent, sep, name = pair.partition("=")
        if not sep:
            raise SystemExit(f"--policy expects agent=name, got {pair!r}")
        policies[agent] = name
    return policies


def _parse_interventions(specs: list[str]) -> list[tuple[int, str]]:
    schedule = []
    for spec in specs:
        name, sep, tick = spec.partition("@")
        schedule.append((int(tick) if sep else 0, name))
    return sorted(schedule)


def run_investigation(scenario: Scenario, seed: int, policies: dict[str, str], schedule: list[tuple[int, str]]) -> Engine:
    """Run to completion, applying each intervention once its tick has finished."""
    engine = Engine.start(scenario, seed, policies)
    pending = list(schedule)
    while engine.state.status == "running":
        while pending and pending[0][0] <= engine.state.tick:
            engine.intervene(pending.pop(0)[1])
        engine.step()
    return engine


def _pct(r: dict) -> str:
    return f"{r['num']}/{r['den']}" + (f" ({r['pct']}%)" if r["pct"] is not None else " (n/a)")


def print_evaluation(scenario: Scenario, result: dict) -> None:
    name = lambda i: scenario.entities[i].name if i in scenario.entities else str(i)  # noqa: E731
    print("\n=== Evaluation ===")
    print(f"Outcome:              {result['outcome'].upper()}")
    print(f"Accused:              {name(result['accused']) if result['accused'] else 'nobody'}" + (f" at tick {result['accusation_tick']}" if result["accused"] else ""))
    print(f"Culprit (truth):      {name(result['culprit'])}")
    if result["accusation_supported"] is not None:
        print(f"Met standard of proof: {'yes' if result['accusation_supported'] else 'no'} (reference reasoner on what the accuser held)")
    ev = result["evidence"]
    print(f"Key evidence found:   {_pct(ev['key_discovered'])}   held by lead: {_pct(ev['key_held_by_lead'])}")
    print(f"All evidence found:   {_pct(ev['all_discovered'])}")
    print(f"Key facts established by lead: {_pct(result['key_facts']['established_by_lead'])}")
    cl = result["claims"]
    print(f"Public claims by agents: {cl['published_by_agents']}   false: {_pct(cl['false'])}   false retracted: {_pct(cl['false_retracted'])}")
    print(f"Unsupported guilt claims: {_pct(cl['unsupported_guilt'])}")
    for claim in cl["items"]:
        flags = ["true" if claim["true"] else "FALSE" if claim["true"] is False else "unknown", "supported" if claim["supported"] else "unsupported"]
        if claim["retracted"]:
            flags.append(f"retracted t{claim['retracted_tick']}")
        print(f"    t{claim['tick']:>2} {claim['by']:>9}: {describe_proposition(scenario, claim['proposition'])}  [{', '.join(flags)}]")
    co = result["contradictions"]
    print(f"Inherent contradictions recognized: {_pct(co['inherent_recognized_by_team'])}   resolved correctly (all agents): {_pct(co['resolved_correctly'])}")
    print("Per agent:")
    for agent_id, a in result["agents"].items():
        prime = name(a["prime_suspect"]) if a["prime_suspect"] else "nobody"
        print(f"    {agent_id:>8}: belief accuracy {_pct(a['belief_accuracy'])}, false beliefs {len(a['false_beliefs'])}, prime suspect {prime}, evidence held {a['evidence_held']}")
    ef = result["effort"]
    print(f"Effort: {ef['ticks']} ticks, {ef['actions']} actions ({ef['waits']} waits), {ef['inspections']} searches ({ef['empty_inspections']} empty, {ef['redundant_inspections']} redundant), {ef['requests']} requests")
    de = result["deception"]
    if de["answers_with_withholding"] or de["escalations"]:
        print(f"Deception: {de['answers_with_withholding']} answers held records back ({', '.join(de['records_withheld'])}); key records affected {_pct(de['key_records_withheld'])}")
        print(f"    noticed by the requester: {_pct(de['noticed'])}   withheld records that reached the requester anyway: {_pct(de['recovered'])}")
        for item in de["items"]:
            noticed = f"noticed t{item['noticed_tick']}" if item["noticed_tick"] is not None else "never noticed"
            print(f"    t{item['tick']:>2} {item['by']} kept {', '.join(item['evidence'])} from {item['from']} ({item['request']}): {noticed}")
        for esc in de["escalations"]:
            print(f"    t{esc['tick']:>2} {esc['by']} took direct access to {len(esc['sources'])} sources over {esc['against']}'s head")
    te = result["testimony"]
    if te["statements"]:
        print(f"Testimony: {te['statements']} statements ({te['passed_on']} passed on); without grounds {_pct(te['without_grounds'])}; false {_pct(te['false'])}")
        print(f"    false statements ever accepted: {_pct(te['false_ever_accepted'])}   still accepted at close: {_pct(te['false_accepted_at_close'])}")
        print(f"    listeners who came to doubt a speaker who told them something false: {_pct(te['false_speakers_impeached'])}   who told them only the truth: {_pct(te['truthful_speakers_impeached'])}")
        for item in te["items"]:
            truth = "true" if item["true"] else "FALSE" if item["true"] is False else "unknown"
            how = f"passing on {item['voice']}" if item["passed_on"] else f"grounds: {item['grounds']}"
            path = " -> ".join(f"{s['stance']} t{s['tick']}" for s in item["stances"])
            print(f"    t{item['tick']:>2} {item['speaker']} to {item['recipient']}: {describe_proposition(scenario, item['proposition'])}  [{truth}; {how}; {path}]")
    if result["provenance"]:
        print("Evidence behind the accusation:")
        for p in result["provenance"]:
            print(f"    {p['id']} {p['title']} ({p['kind']}): first found by {p['first_found_by']} at t{p['first_found_tick']}, custody {' -> '.join(p['chain'])}")


def cmd_demo(args: argparse.Namespace) -> int:
    scenario = _load(args.scenario)
    try:
        engine = run_investigation(scenario, args.seed, _parse_policies(args.policy), _parse_interventions(args.intervene))
    except EngineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(evaluate(scenario, engine.state, engine.events), indent=2))
        return 0
    print(f"{scenario.case.title}  (seed {args.seed})")
    print(scenario.case.briefing)
    if not args.quiet:
        hidden = {"BeliefsRevised", "RequestSent", "EvidenceObserved"}
        for event in engine.events:
            if event.type == "TickStarted":
                print(f"\n-- tick {event.tick} --")
                continue
            if event.type in hidden and not (event.type == "BeliefsRevised" and event.data["prime_before"] != event.data["prime_after"]):
                continue
            if event.type == "ActionTaken" and event.data["action"]["type"] == "wait":
                continue
            indent = "  " if event.type in ("ActionTaken", "ActionRejected", "InterventionApplied") else "      "
            print(indent + narrate(scenario, event))
    print_evaluation(scenario, evaluate(scenario, engine.state, engine.events))
    checks = verify_run(scenario, engine.events)
    print("\n=== Replay verification ===")
    for label in ("chain", "fold", "decisions", "policies"):
        check = checks[label]
        mark = "ok" if check["ok"] else "skipped" if check["ok"] is None else "FAILED"
        print(f"{label:>10}: {mark:7} {check['detail']}")
    print(f"head hash: {checks['head_hash']}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    names = [args.scenario] if args.scenario else bundled_scenario_ids()
    failed = False
    for name in names:
        try:
            scenario = _load(name)
            problems = lint(scenario)
        except Exception as exc:
            problems = [str(exc)]
            scenario = None
        if problems:
            failed = True
            print(f"{name}: INVALID")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"{name}: ok  (v{scenario.version}, {len(scenario.evidence)} evidence records, {len(scenario.agents)} agents, hash {scenario.content_hash[:12]})")
            for accuser, found in reach_report(scenario)["accusers"].items():
                how = {
                    "cooperative": "solvable by a cooperative team",
                    "escalation": "solvable ONLY if this agent takes over an operator's sources (no honest run can solve it)",
                    "no": "cannot assemble the case",
                }[found["solvable"]]
                print(f"  {accuser}: {how}; records reachable {len(found['cooperative'])} cooperatively, "
                      f"{len(found['escalation'])} more by escalation ({', '.join(found['escalation']) or 'none'}), "
                      f"{len(found['never'])} never ({', '.join(found['never']) or 'none'})")
    return 1 if failed else 0


def cmd_sweep(args: argparse.Namespace) -> int:
    scenario = _load(args.scenario)
    first, _, last = args.seeds.partition("-")
    seeds = range(int(first), int(last or first) + 1)
    policies = _parse_policies(args.policy)
    schedule = _parse_interventions(args.intervene)
    rows = []
    for seed in seeds:
        engine = run_investigation(scenario, seed, policies, schedule)
        row = summary_row(scenario, engine.state, engine.events)
        rows.append(row)
        if args.json:
            print(json.dumps(row))
    if not args.json:
        columns = ["seed", "outcome", "accused", "supported", "ticks", "actions", "key_evidence", "all_evidence", "claims", "false_claims", "false_retracted"]
        print("  ".join(f"{c:>15}" for c in columns))
        for row in rows:
            print("  ".join(f"{str(row[c]):>15}" for c in columns))
    summary = sweep_summary(rows)
    print(json.dumps({"summary": summary}) if args.json else f"\n{summary}")
    return 0


def median(values: list[int]) -> int | float | None:
    """The statistical median: for an even count, the mean of the two middle values.

    Whole results stay integers, so a table shows 17 and 16.5, never 17.0.
    This is reporting only; nothing computed here enters an event.
    """
    if not values:
        return None
    middle = statistics.median(values)
    return int(middle) if middle == int(middle) else middle


def sweep_summary(rows: list[dict]) -> dict:
    """Aggregate the per-run rows of a sweep."""
    outcomes = Counter(row["outcome"] for row in rows)
    solved = [row["ticks"] for row in rows if row["outcome"] == "solved"]
    return {
        "runs": len(rows),
        "outcomes": dict(sorted(outcomes.items())),
        # Right culprit *and* the reference standard met on what the accuser held: not a lucky guess.
        "solved_and_supported": sum(1 for row in rows if row["outcome"] == "solved" and row["supported"]),
        # Wrong person, and the reference standard was met all the same: the rules were
        # satisfied by evidence that misleads. Conforming to the standard is not being right.
        "wrong_but_supported": sum(1 for row in rows if row["outcome"] == "wrong_accusation" and row["supported"]),
        "median_ticks_when_solved": median(solved),
        "false_claims": sum(row["false_claims"] for row in rows),
        "false_claims_retracted": sum(row["false_retracted"] for row in rows),
        "withheld_answers": sum(row["withheld_answers"] for row in rows),
        "withholding_noticed": sum(row["withholding_noticed"] for row in rows),
        "runs_with_escalation": sum(1 for row in rows if row["escalations"]),
        # Right or wrong, and justified or not, kept apart.
        "categories": dict(sorted(Counter(row["category"] for row in rows).items())),
        "false_statements": sum(row["false_statements"] for row in rows),
        "false_statements_ever_accepted": sum(row["false_ever_accepted"] for row in rows),
        "false_statements_accepted_at_close": sum(row["false_accepted_at_close"] for row in rows),
    }


def _lab_manifest(args: argparse.Namespace) -> dict:
    return lab.load_manifest(args.manifest)


def cmd_lab_list(args: argparse.Namespace) -> int:
    manifest = _lab_manifest(args)
    print(manifest["label"])
    drift = lab.baseline_drift(manifest)
    frozen = manifest["frozen"]
    print(f"registered against rules {frozen['rules_version']}, engine {frozen['engine_version']}, fingerprint {frozen['behaviour_fingerprint']}: "
          + ("this build" if not drift else "NOT this build (" + "; ".join(drift) + ")"))
    print(f"\n{'challenge':<28}{'kind':<11}{'category':<21}{'culprit':<10}policies")
    for challenge in manifest["challenges"]:
        policies = ", ".join(f"{a}={p}" for a, p in sorted(challenge.get("policies", {}).items())) or ("baseline" if challenge["kind"] == "playable" else "-")
        print(f"{challenge['id']:<28}{challenge['kind']:<11}{challenge['category']:<21}{challenge['culprit']:<10}{policies}")
    print("\ncollections: all, playable, reasoning, or a category name")
    return 0


def cmd_lab_show(args: argparse.Namespace) -> int:
    manifest = _lab_manifest(args)
    print(lab.describe(manifest, lab.find_challenge(manifest, args.challenge)))
    return 0


def cmd_lab_check(args: argparse.Namespace) -> int:
    """Build every variant through the models and the lint, and compare the build with the registered baseline."""
    manifest = _lab_manifest(args)
    failed = False
    for variant_id in manifest["variants"]:
        try:
            scenario = lab.build_variant(manifest, variant_id)
        except lab.ChallengeError as exc:
            failed = True
            print(f"{variant_id}: REJECTED\n  {exc}")
            continue
        solvable = ", ".join(f"{a}: {e['solvable']}" for a, e in reach_report(scenario)["accusers"].items())
        print(f"{variant_id}: ok  ({scenario.id} {scenario.version}, hash {scenario.content_hash[:12]}, solvable {solvable})")
    drift = lab.baseline_drift(manifest)
    print("baseline: " + ("the build is the one registered" if not drift else "DRIFT\n  " + "\n  ".join(drift)))
    return 1 if failed or drift else 0


def cmd_lab_export(args: argparse.Namespace) -> int:
    manifest = _lab_manifest(args)
    lab.build_variant(manifest, args.variant)  # refuse to write a file the lint would reject
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(lab.variant_data(manifest, args.variant), handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"wrote {args.out}. Play it with: python -m caseforge demo --scenario {args.out} --seed 7")
    return 0


def cmd_lab_run(args: argparse.Namespace) -> int:
    import os

    manifest = _lab_manifest(args)
    progress = None if args.json else (lambda line: print(f"  {line}", file=sys.stderr, flush=True))
    results = lab.run_lab(
        manifest, args.challenge, lab.parse_seeds(args.seeds), replay=args.replay,
        overrides=_parse_policies(args.policy), allow_drift=args.allow_drift, progress=progress,
    )
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8", newline="\n") as handle:
            json.dump(results, handle, indent=1)
            handle.write("\n")
        with open(os.path.join(args.out, "report.md"), "w", encoding="utf-8", newline="\n") as handle:
            handle.write(lab.render_markdown(results))
    print(json.dumps(results) if args.json else lab.render_terminal(results))
    if args.out and not args.json:
        print(f"\nwrote {os.path.join(args.out, 'results.json')} and {os.path.join(args.out, 'report.md')}")
    violations = sum(entry["aggregate"]["verdicts"]["contract_violation"] for entry in results["playable"].values())
    violations += sum(1 for entry in results["reasoning"].values() if entry["result"]["verdict"] == "contract_violation")
    return 1 if violations else 0  # falling short of an ideal is a finding, not an error


def cmd_lab_reproduce(args: argparse.Namespace) -> int:
    """One run of one challenge, with its original configuration, checked and narrated."""
    manifest = _lab_manifest(args)
    challenge = lab.find_challenge(manifest, args.challenge)
    drift = lab.baseline_drift(manifest)
    if drift:
        print("warning: this build is not the one the manifest was registered against: " + "; ".join(drift), file=sys.stderr)
    if challenge["kind"] == "reasoning":
        row = lab.run_reasoning(challenge)
        if args.json:
            print(json.dumps(row, indent=2))
            return 0
        print(lab.describe(manifest, challenge))
        print(f"\nstandard of proof met for: {row['convicted'] or 'nobody'}   (culprit: {challenge['culprit']})   prime suspect: {row['prime_suspect'] or 'nobody'}")
        for suspect, a in row["suspects"].items():
            print(f"    {suspect:>8}: score {a['score']}, opportunity {a['opportunity']}, means {'yes' if a['means'] else 'no'}, motive {a['motive']}")
        for key, belief in row["beliefs"].items():
            print(f"    {key}: {belief['status']} ({belief['support']} for, {belief['contra']} against)")
        for voice, seen in row["credibility"].items():
            print(f"    {voice}: {seen['standing']}")
        _print_expectations(challenge, row["expectations"], row["verdict"])
        return 0
    if args.seed is None:
        raise SystemExit("a playable challenge is reproduced for one seed: pass --seed N")
    row, run = lab.run_playable(manifest, challenge, args.seed, replay=True, overrides=_parse_policies(args.policy))
    if args.json:
        print(json.dumps({"row": row, "evaluation": run.result}, indent=2))
        return 0
    scenario = run.scenario
    print(f"{challenge['id']}  seed {args.seed}  scenario {scenario.id} {scenario.version} ({scenario.content_hash[:12]})")
    print(challenge["question"])
    if args.timeline:
        hidden = {"BeliefsRevised", "RequestSent", "EvidenceObserved"}
        for event in run.events:
            if event.type == "TickStarted":
                print(f"\n-- tick {event.tick} --")
            elif event.type in hidden and not (event.type == "BeliefsRevised" and event.data["prime_before"] != event.data["prime_after"]):
                continue
            elif not (event.type == "ActionTaken" and event.data["action"]["type"] == "wait"):
                print(("  " if event.type in ("ActionTaken", "ActionRejected", "InterventionApplied") else "      ") + narrate(scenario, event))
    print_evaluation(scenario, run.result)
    print(f"\ncategory: {row['category']}   head hash: {row['head']}")
    print("replay: " + ", ".join(f"{level} {'ok' if ok else 'FAILED'}" for level, ok in row["replay"].items()))
    _print_expectations(challenge, row["expectations"], row["verdict"])
    return 0


def _print_expectations(challenge: dict, held: dict, verdict: str) -> None:
    print("\nexpectations:")
    for expectation in challenge["expectations"]:
        value = held[expectation["id"]]
        mark = "holds" if value else "n/a" if value is None else "FAILS"
        print(f"    [{expectation['kind']:<8}] {mark:<6} {expectation['says']}")
    meaning = {
        "meets_ideal": "every expectation holds",
        "falls_short": "an ideal is not reached: a limit of the policy or the reasoner, not a defect",
        "invalid_instance": "a design condition is not met: this run does not test what the challenge is about",
        "contract_violation": "a contract is broken: a software defect",
    }[verdict]
    print(f"verdict: {verdict} ({meaning})")


LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def non_local_warning(host: str) -> str | None:
    """The API has no authentication: reveal and delete are open routes. Say so when it is not bound to this machine."""
    if host in LOCAL_HOSTS:
        return None
    return (
        f"warning: serving on {host}, which is not this machine only. The API has no authentication: anyone who can reach "
        "it can read every run, reveal solutions, delete runs and start laboratory executions. CaseForge is a local tool; "
        "put it behind something that authenticates before exposing it. It answers only to Host names it was told about "
        "(the address it is bound to, unless that is a wildcard such as 0.0.0.0, and any --allow-host): that blocks DNS "
        "rebinding, it does not authenticate anyone."
    )


def cmd_serve(args: argparse.Namespace) -> int:
    import os

    import uvicorn

    from .netguard import allowed_hosts, hosts_from_env

    try:
        names = allowed_hosts(args.host, [*args.allow_host, *hosts_from_env(os.environ.get("CASEFORGE_ALLOWED_HOSTS"))])
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    warning = non_local_warning(args.host)
    if warning:
        print(warning, file=sys.stderr)

    # Hosts besides loopback that the server will answer to: the address it was deliberately bound to
    # (never a wildcard) and each --allow-host. The factory reads them back from the environment.
    os.environ["CASEFORGE_ALLOWED_HOSTS"] = ",".join(sorted(names - set(LOCAL_HOSTS)))
    if args.db:
        os.environ["CASEFORGE_DB"] = args.db
    uvicorn.run("caseforge.api:create_app", factory=True, host=args.host, port=args.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caseforge", description="CaseForge: a multi-agent investigation laboratory.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--scenario", default=DEFAULT_SCENARIO, help="bundled scenario id or path to a .json file")
        p.add_argument("--policy", action="append", default=[], metavar="AGENT=NAME", help="override an agent's policy, e.g. okafor=hasty")
        p.add_argument("--intervene", action="append", default=[], metavar="ID@TICK", help="apply an intervention after TICK has finished")
        p.add_argument("--json", action="store_true", help="machine-readable output")

    demo = sub.add_parser("demo", help="run one investigation and print what happened")
    common(demo)
    demo.add_argument("--seed", type=int, default=7)
    demo.add_argument("--quiet", action="store_true", help="skip the timeline, print only the evaluation")
    demo.set_defaults(func=cmd_demo)

    validate = sub.add_parser("validate", help="lint scenarios")
    validate.add_argument("scenario", nargs="?", help="scenario id or .json path (default: all bundled)")
    validate.set_defaults(func=cmd_validate)

    sweep = sub.add_parser("sweep", help="run many seeds and tabulate outcomes")
    common(sweep)
    sweep.add_argument("--seeds", default="0-19", help="inclusive range, e.g. 0-49")
    sweep.set_defaults(func=cmd_sweep)

    serve = sub.add_parser("serve", help="start the API and web interface")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--allow-host", action="append", default=[], metavar="NAME",
        help="also answer to this Host name (repeatable); only localhost, 127.0.0.1 and ::1 are answered to by default. Not authentication",
    )
    serve.add_argument("--db", help="path to the SQLite file (default: ./caseforge.sqlite3)")
    serve.set_defaults(func=cmd_serve)

    lab_parser = sub.add_parser("lab", help="counterfactual laboratory: pre-registered challenges against the frozen rules")
    lab_sub = lab_parser.add_subparsers(dest="lab_command", required=True)

    def lab_command(name: str, func, text: str) -> argparse.ArgumentParser:
        p = lab_sub.add_parser(name, help=text)
        p.add_argument("--manifest", help="path to a manifest (default: the bundled collection)")
        p.set_defaults(func=func)
        return p

    lab_command("list", cmd_lab_list, "the challenges and collections")
    lab_command("show", cmd_lab_show, "one challenge: what was changed, who did it, what is expected").add_argument("challenge")
    lab_command("check", cmd_lab_check, "build and lint every variant; compare the build with the registered baseline")
    lab_export = lab_command("export", cmd_lab_export, "write a variant as an ordinary scenario file")
    lab_export.add_argument("variant")
    lab_export.add_argument("--out", required=True)
    lab_run = lab_command("run", cmd_lab_run, "run challenges over a range of seeds")
    lab_run.add_argument("challenge", nargs="*", help="challenge ids or collections (default: all)")
    lab_run.add_argument("--seeds", default="0-39", help="inclusive range, e.g. 0-39")
    lab_run.add_argument("--policy", action="append", default=[], metavar="AGENT=NAME", help="override a policy; the result is then not the registered experiment")
    lab_run.add_argument("--replay", choices=("every", "first", "none"), default="first", help="which runs to verify by replay")
    lab_run.add_argument("--out", metavar="DIR", help="write results.json and report.md here")
    lab_run.add_argument("--json", action="store_true", help="print the structured results")
    lab_run.add_argument("--allow-drift", action="store_true", help="run although the build differs from the registered baseline; the drift is recorded")
    lab_reproduce = lab_command("reproduce", cmd_lab_reproduce, "run one case again with its original configuration")
    lab_reproduce.add_argument("challenge")
    lab_reproduce.add_argument("--seed", type=int)
    lab_reproduce.add_argument("--policy", action="append", default=[], metavar="AGENT=NAME")
    lab_reproduce.add_argument("--timeline", action="store_true", help="print what happened, tick by tick")
    lab_reproduce.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except lab.ChallengeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
