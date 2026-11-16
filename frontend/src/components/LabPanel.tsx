import { useState } from "react";
import type { Check, Comparison, RunSummary, Snapshot, VerifyReport } from "../api";
import { Chip, Empty, Section, shortHash } from "./ui";

interface Props {
  snapshot: Snapshot;
  runs: RunSummary[];
  busy: boolean;
  verify: VerifyReport | null;
  comparison: Comparison | null;
  onIntervene: (id: string) => void;
  onVerify: () => void;
  onBranch: (tick: number, label: string) => void;
  onCompare: (other: string) => void;
  onOpenRun: (id: string) => void;
  onDelete: () => void;
}

function CheckRow({ label, hint, check }: { label: string; hint: string; check: Check }) {
  const tone = check.ok === true ? "believed" : check.ok === null ? "neutral" : "rejected";
  return (
    <tr title={hint}>
      <td>{label}</td>
      <td>
        <Chip tone={tone}>{check.ok === true ? "pass" : check.ok === null ? "skipped" : "FAIL"}</Chip>
      </td>
      <td className="muted">{check.detail}</td>
    </tr>
  );
}

const METRIC_LABELS: [string, string][] = [
  ["outcome", "Outcome"],
  ["accused", "Accused"],
  ["supported", "Standard of proof met"],
  ["ticks", "Ticks"],
  ["actions", "Actions"],
  ["key_evidence", "Key evidence found"],
  ["all_evidence", "All evidence found"],
  ["claims", "Public claims"],
  ["false_claims", "False claims"],
  ["false_retracted", "False claims retracted"],
  ["unsupported_guilt_claims", "Unsupported accusations published"],
  ["withheld_answers", "Answers that held records back"],
  ["withholding_noticed", "Withholding noticed"],
  ["escalations", "Escalations"],
];

export default function LabPanel({ snapshot, runs, busy, verify, comparison, onIntervene, onVerify, onBranch, onCompare, onOpenRun, onDelete }: Props) {
  const run = snapshot.run;
  const readOnly = !run.continuable;
  const live = snapshot.is_latest && run.status === "running" && !readOnly;
  const [label, setLabel] = useState("");
  const [other, setOther] = useState("");
  const others = runs.filter((r) => r.id !== run.id && r.compatible);
  const canBranch = snapshot.status === "running";

  // A report describes one exact log. It is current only while that log is still the head.
  const verifyMine = verify && verify.run_id === run.id ? verify : null;
  const verifyStale = !!verifyMine && verifyMine.head_hash !== run.head_hash;
  const headOf = (id: string) => (id === run.id ? run.head_hash : runs.find((r) => r.id === id)?.head_hash ?? null);
  const comparisonMine = comparison && (comparison.a.run.id === run.id || comparison.b.run.id === run.id) ? comparison : null;
  const comparisonStale = !!comparisonMine && [comparisonMine.a.run, comparisonMine.b.run].some((side) => headOf(side.id) !== side.head_hash);
  const comparedWith = comparisonMine ? (comparisonMine.a.run.id === run.id ? comparisonMine.b.run.id : comparisonMine.a.run.id) : null;

  return (
    <div className="lab">
      <Section title="Interventions" aside={<span className="muted small">recorded as events, replayed exactly</span>}>
        {readOnly && <div className="muted small" data-testid="readonly-note">This run is read-only (see the notice above the panels): interventions are off. You can still branch from a tick the current rules reproduce.</div>}
        {!live && !readOnly && <div className="muted small">{run.status === "closed" ? "The case is closed. Branch from an earlier tick to try an intervention." : "You are viewing the past. Return to the latest tick, or branch from here."}</div>}
        <ul className="cards">
          {snapshot.interventions.map((item) => (
            <li key={item.id} className="card">
              <div className="card-head">
                <b>{item.label}</b>
                {item.applied && <Chip tone="believed">applied</Chip>}
              </div>
              <p>{item.description}</p>
              <button disabled={busy || !live || item.applied} onClick={() => onIntervene(item.id)}>
                {item.applied ? "Already applied" : "Apply now"}
              </button>
            </li>
          ))}
        </ul>
      </Section>

      <Section title={`Branch from tick ${snapshot.tick}`}>
        <p className="muted small">Creates a new run that shares this run's history up to tick {snapshot.tick}. Left alone, a branch replays its parent exactly; an intervention or a policy change makes it diverge.</p>
        <div className="row">
          <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Label for the branch (optional)" maxLength={80} aria-label="Branch label" />
          <button disabled={busy || !canBranch} onClick={() => onBranch(snapshot.tick, label)} title={canBranch ? "" : "The case is closed at this tick: scrub back first"}>
            Branch here
          </button>
        </div>
        {run.parent_run_id && (
          <div className="muted small">
            This run is a branch of{" "}
            <button className="link" onClick={() => onOpenRun(run.parent_run_id!)}>
              {run.parent_run_id}
            </button>{" "}
            at tick {run.fork_tick}.
          </div>
        )}
      </Section>

      <Section title="Replay verification" aside={<button disabled={busy} onClick={onVerify}>Verify this run</button>}>
        {!verifyMine ? (
          <>
            <p className="muted small" data-testid="compatibility-note">
              Compatibility with the current rules: <b>{run.compatibility?.state.replace("_", " ") ?? "not applicable"}</b>
              {run.compatibility && <> ({run.compatibility.detail})</>}
            </p>
            <p className="muted small">Re-checks the stored log four ways: hash chain, state rebuild, replay of recorded decisions, and a full re-simulation from the seed.</p>
          </>
        ) : (
          <div data-testid="verify-report" data-stale={verifyStale ? "true" : "false"}>
            {verifyStale ? (
              <div className="banner stale" role="status">
                <span>
                  <Chip tone="disputed">out of date</Chip> This report is about an earlier log ({verifyMine.events} events, tick {verifyMine.tick}). The run now has {run.seq + 1} events. Verify again to check the current log.
                </span>
              </div>
            ) : (
              <div className="muted small">
                Checked log: {verifyMine.events} events up to tick {verifyMine.tick}, the current head of this run.
              </div>
            )}
            <table className={`table small ${verifyStale ? "stale" : ""}`}>
              <tbody>
                <CheckRow label="Hash chain" hint="Every event's hash matches its content and predecessor" check={verifyMine.chain} />
                <CheckRow label="State rebuild" hint="Folding the stored events yields a valid state" check={verifyMine.fold} />
                <CheckRow label="Decision replay" hint="Recorded decisions fed back through the engine reproduce the log" check={verifyMine.decisions} />
                <CheckRow label="Re-simulation" hint="Policies run again from the seed reproduce the log (deterministic policies only)" check={verifyMine.policies} />
              </tbody>
            </table>
            <div className="muted small">
              head hash <code>{shortHash(verifyMine.head_hash)}</code> · stored log matches memory: {verifyMine.stored_matches_memory ? "yes" : "NO"}
            </div>
          </div>
        )}
      </Section>

      <Section title="Compare with another run">
        {others.length === 0 ? (
          <Empty>Create or branch another run to compare outcomes.</Empty>
        ) : (
          <div className="row">
            <select value={other} onChange={(e) => setOther(e.target.value)} aria-label="Run to compare with">
              <option value="">Choose a run...</option>
              {others.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label || r.id} · seed {r.seed} · tick {r.tick} · {r.status}
                </option>
              ))}
            </select>
            <button disabled={busy || !other} onClick={() => onCompare(other)}>
              Compare
            </button>
          </div>
        )}
        {comparisonMine && comparison && (
          <div data-testid="comparison" data-stale={comparisonStale ? "true" : "false"} className={comparisonStale ? "stale" : ""}>
            {comparisonStale && (
              <div className="banner stale" role="status">
                <span>
                  <Chip tone="disputed">out of date</Chip> One of these runs has changed since the comparison was made (they had {comparison.a.run.seq + 1} and {comparison.b.run.seq + 1} events then).
                </span>
                <button disabled={busy || !comparedWith} onClick={() => comparedWith && onCompare(comparedWith)}>
                  Compare again
                </button>
              </div>
            )}
            <p className="small">
              {comparison.identical ? (
                "The two logs are identical, event for event."
              ) : (
                <>
                  The runs share {comparison.common_events} events and diverge after tick {comparison.divergence?.tick}:
                </>
              )}
            </p>
            {comparison.divergence && (
              <ul className="plain small">
                <li>
                  <b>{comparison.a.run.label || comparison.a.run.id}:</b> {comparison.divergence.a[0]?.summary ?? "(log ends)"}
                </li>
                <li>
                  <b>{comparison.b.run.label || comparison.b.run.id}:</b> {comparison.divergence.b[0]?.summary ?? "(log ends)"}
                </li>
              </ul>
            )}
            <table className="table small">
              <thead>
                <tr>
                  <th />
                  <th>{comparison.a.run.label || comparison.a.run.id}</th>
                  <th>{comparison.b.run.label || comparison.b.run.id}</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Interventions</td>
                  <td>{comparison.a.run.interventions.join(", ") || "none"}</td>
                  <td>{comparison.b.run.interventions.join(", ") || "none"}</td>
                </tr>
                <tr>
                  <td>Policies</td>
                  <td>{Object.entries(comparison.a.run.policies).filter(([, p]) => p !== "baseline").map(([a, p]) => `${a}=${p}`).join(", ") || "all baseline"}</td>
                  <td>{Object.entries(comparison.b.run.policies).filter(([, p]) => p !== "baseline").map(([a, p]) => `${a}=${p}`).join(", ") || "all baseline"}</td>
                </tr>
                {comparison.a.metrics && comparison.b.metrics ? (
                  METRIC_LABELS.map(([key, text]) => {
                    const left = String(comparison.a.metrics![key] ?? "-");
                    const right = String(comparison.b.metrics![key] ?? "-");
                    return (
                      <tr key={key} className={left !== right ? "differs" : ""}>
                        <td>{text}</td>
                        <td>{left}</td>
                        <td>{right}</td>
                      </tr>
                    );
                  })
                ) : (
                  <>
                    <tr>
                      <td>Evidence found</td>
                      <td>
                        {comparison.a.progress.evidence_discovered}/{comparison.a.progress.evidence_total}
                      </td>
                      <td>
                        {comparison.b.progress.evidence_discovered}/{comparison.b.progress.evidence_total}
                      </td>
                    </tr>
                    <tr>
                      <td colSpan={3} className="muted">
                        Outcome metrics appear once both cases are closed or revealed.
                      </td>
                    </tr>
                  </>
                )}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="This run">
        <dl className="facts">
          <dt>Run id</dt>
          <dd>
            <code>{run.id}</code>
          </dd>
          <dt>Scenario</dt>
          <dd>
            {run.scenario_id} v{run.scenario_version}
          </dd>
          <dt>Seed</dt>
          <dd>{run.seed}</dd>
          <dt>Events</dt>
          <dd>{run.seq + 1}</dd>
          <dt>Head hash</dt>
          <dd>
            <code title={run.head_hash}>{shortHash(run.head_hash)}</code>
          </dd>
        </dl>
        <button className="danger" disabled={busy} onClick={onDelete}>
          Delete this run
        </button>
      </Section>
    </div>
  );
}
