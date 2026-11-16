import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  type LabAggregate,
  type LabChallenge,
  type LabExecution,
  type LabExpectation,
  type LabOverview,
  type LabReasoningResult,
  type LabRunRow,
  type OutcomeCategory,
} from "../api";
import { Chip, Empty, Section } from "./ui";

// The collection of counterfactual challenges, as recorded and as re-run on request.
// Three kinds of figure are shown and each says which it is: STORED (the registered collection,
// read from disk), EXECUTED (a few seeds run just now on this machine) and REPLAY (the same with
// every replay level checked). Nothing here runs because a page was opened.

const CATEGORY_LABEL: Record<OutcomeCategory, string> = {
  correct_supported: "correct, supported",
  correct_unsupported: "correct, unsupported",
  wrong_supported: "wrong, supported",
  wrong_unsupported: "wrong, unsupported",
  unresolved: "unresolved",
};

const CATEGORY_NOTE: Record<OutcomeCategory, string> = {
  correct_supported: "The right person was accused and the standard of proof was met.",
  correct_unsupported: "The right person was accused, but the standard of proof was not met.",
  wrong_supported: "Someone else was accused although the standard of proof was met. Supported is not the same as true.",
  wrong_unsupported: "Someone else was accused and the standard of proof was not met.",
  unresolved: "Nobody was accused before the case closed.",
};

const CATEGORIES = Object.keys(CATEGORY_LABEL) as OutcomeCategory[];

function parseSeeds(text: string): number[] | string {
  const seeds: number[] = [];
  for (const part of text.split(",").map((p) => p.trim()).filter(Boolean)) {
    const range = /^(\d+)\s*-\s*(\d+)$/.exec(part);
    if (range) {
      const first = Number(range[1]);
      const last = Number(range[2]);
      if (last < first || last - first > 99) return `"${part}" is not a usable range`;
      for (let seed = first; seed <= last; seed++) seeds.push(seed);
    } else if (/^\d+$/.test(part)) {
      seeds.push(Number(part));
    } else {
      return `"${part}" is not a seed`;
    }
  }
  return seeds.length ? seeds : "name at least one seed, for example 0-4 or 3,7";
}

const pair = (p: [number, number]) => `${p[0]}/${p[1]}`;
const num = (value: number | null | undefined) => (value === null || value === undefined ? "n/a" : String(value));

function OutcomeBar({ aggregate }: { aggregate: LabAggregate }) {
  return (
    <div className="lab-bar" role="img" aria-label={CATEGORIES.map((c) => `${CATEGORY_LABEL[c]} ${aggregate.categories[c]}`).join(", ")}>
      {CATEGORIES.filter((c) => aggregate.categories[c] > 0).map((c) => (
        <span key={c} className={`lab-seg lab-${c}`} style={{ flexGrow: aggregate.categories[c] }} title={`${CATEGORY_LABEL[c]}: ${aggregate.categories[c]} of ${aggregate.runs}`} />
      ))}
    </div>
  );
}

function Legend() {
  return (
    <ul className="lab-legend plain">
      {CATEGORIES.map((c) => (
        <li key={c} title={CATEGORY_NOTE[c]}>
          <span className={`lab-swatch lab-${c}`} /> {CATEGORY_LABEL[c]}
        </li>
      ))}
    </ul>
  );
}

function Expectations({ items, reveal }: { items: LabExpectation[]; reveal: boolean }) {
  return (
    <table className="table" data-testid="lab-expectations">
      <thead>
        <tr>
          <th>Expectation</th>
          <th>Kind</th>
          <th>Predicted</th>
          <th>Observed</th>
          <th className="num">Held</th>
          <th>Prediction</th>
        </tr>
      </thead>
      <tbody>
        {items.map((e) => (
          <tr key={e.id} className={e.prediction_right === false ? "differs" : ""}>
            <td>
              <code>{e.id}</code>
              {reveal && e.says && <div className="small muted">{e.says}</div>}
            </td>
            <td>{e.kind}</td>
            <td>{e.predicted}</td>
            <td>{e.observed.replace("_", " ")}</td>
            <td className="num">
              {e.held}/{e.of}
            </td>
            <td>{e.prediction_right === null ? "n/a" : e.prediction_right ? <Chip tone="believed">right</Chip> : <Chip tone="rejected">wrong</Chip>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Measures({ a }: { a: LabAggregate }) {
  const rows: [string, string, string][] = [
    ["Median ticks (all runs)", num(a.median_ticks), "Ticks until the case closed, over every run."],
    ["Median ticks when solved", `${num(a.median_ticks_when_solved)}${a.ticks_range_when_solved ? ` (range ${a.ticks_range_when_solved[0]}-${a.ticks_range_when_solved[1]})` : ""}`, "Only runs that ended in a correct accusation."],
    ["Median actions", num(a.median_actions), "Actions taken by all agents together."],
    ["Decisive items found", pair(a.key_evidence_discovered), "Items the case turns on, found by anyone, over all runs."],
    ["Decisive items held by the accuser", pair(a.key_evidence_held_by_accuser), "What the accusing agent actually held at the time."],
    ["All evidence discovered", pair(a.all_evidence_discovered), ""],
    ["Contradictions recognised", pair(a.contradictions_recognized), "Inherent contradictions the team noticed."],
    ["Contradictions resolved correctly", pair(a.contradictions_resolved_correctly), ""],
    ["Statements made", String(a.statements), "Spoken testimony."],
    ["False statements", String(a.false_statements), "Judged against the ground truth, which only the evaluation reads."],
    ["False statements ever accepted", String(a.false_ever_accepted), "Accepted by a listener at some point."],
    ["False statements accepted at close", String(a.false_accepted_at_close), ""],
    ["False statements unrefuted at close", String(a.false_unrefuted_at_close), "Not rejected by the end, whether or not accepted."],
    ["Credibility revisions", String(a.credibility_revisions), "Times an agent changed its view of a speaker."],
    ["Runs where the accuser impeached someone", `${a.runs_where_accuser_impeached_someone}/${a.runs}`, ""],
    ["Withheld answers / noticed", `${a.withheld_answers} / ${a.withholding_noticed}`, "Answers that left a record out, and how many the requester noticed."],
    ["Runs with escalation", `${a.runs_with_escalation}/${a.runs}`, ""],
  ];
  return (
    <table className="table lab-measures" data-testid="lab-measures">
      <tbody>
        {rows.map(([label, value, hint]) => (
          <tr key={label} title={hint}>
            <td>{label}</td>
            <td className="num">{value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RunTable({
  runs,
  reveal,
  busy,
  onReplay,
  onOpen,
}: {
  runs: LabRunRow[];
  reveal: boolean;
  busy: boolean;
  onReplay?: (seed: number) => void;
  onOpen?: (seed: number) => void;
}) {
  return (
    <div className="lab-scroll">
      <table className="table" data-testid="lab-runs">
        <thead>
          <tr>
            <th>Seed</th>
            <th>Outcome</th>
            {reveal && <th>Accused</th>}
            <th className="num">Ticks</th>
            <th className="num">Decisive found</th>
            <th className="num">False stmts</th>
            <th>Replay</th>
            <th>Verdict</th>
            {(onReplay || onOpen) && <th />}
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.seed} data-testid={`lab-seed-${r.seed}`}>
              <td>{r.seed}</td>
              <td>
                <span className={`lab-swatch lab-${r.category}`} /> {CATEGORY_LABEL[r.category]}
              </td>
              {reveal && <td>{r.accused ?? "nobody"}</td>}
              <td className="num">{r.ticks}</td>
              <td className="num">{pair(r.decisive_found)}</td>
              <td className="num">{r.false_statements}</td>
              <td>{r.replay ? (Object.values(r.replay).every(Boolean) ? "verified" : <Chip tone="rejected">failed</Chip>) : <span className="muted">not run</span>}</td>
              <td>{r.verdict.replace("_", " ")}</td>
              {(onReplay || onOpen) && (
                <td className="lab-actions">
                  {onReplay && (
                    <button className="link" disabled={busy} onClick={() => onReplay(r.seed)} data-testid={`lab-replay-${r.seed}`} title="Run this seed again now and check all four replay levels">
                      replay
                    </button>
                  )}
                  {onOpen && (
                    <button className="link" disabled={busy} onClick={() => onOpen(r.seed)} data-testid={`lab-open-${r.seed}`} title="Start this seed as an ordinary run you can step through">
                      open
                    </button>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReasoningResult({ result }: { result: LabReasoningResult }) {
  return (
    <>
      <p className="small">
        Outcome: <b>{CATEGORY_LABEL[result.category]}</b>. Verdict: <b>{result.verdict.replace("_", " ")}</b>.
      </p>
      <table className="table" data-testid="lab-beliefs">
        <thead>
          <tr>
            <th>Proposition</th>
            <th className="num">Support</th>
            <th className="num">Against</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(result.beliefs).map(([key, b]) => (
            <tr key={key}>
              <td>
                <code>{key}</code>
              </td>
              <td className="num">{b.support}</td>
              <td className="num">{b.contra}</td>
              <td>
                <Chip tone={b.status}>{b.status}</Chip>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <table className="table">
        <thead>
          <tr>
            <th>Suspect</th>
            <th>Opportunity</th>
            <th>Means</th>
            <th>Motive</th>
            <th className="num">Score</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(result.suspects).map(([name, s]) => (
            <tr key={name}>
              <td>{name}</td>
              <td>{s.opportunity}</td>
              <td>{s.means ? "yes" : "no"}</td>
              <td>{s.motive}</td>
              <td className="num">{s.score}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {Object.keys(result.credibility).length > 0 && (
        <p className="small muted">
          Voices judged: {Object.entries(result.credibility).map(([voice, c]) => `${voice} (${c.current?.standing ?? "unknown"})`).join(", ")}
        </p>
      )}
    </>
  );
}

function Detail({ id, maxSeeds, onOpenRun, onClose }: { id: string; maxSeeds: number; onOpenRun: (runId: string) => void; onClose: () => void }) {
  const [reveal, setReveal] = useState(false);
  const [challenge, setChallenge] = useState<LabChallenge | null>(null);
  const [execution, setExecution] = useState<LabExecution | null>(null);
  const [seedText, setSeedText] = useState("0-2");
  const [replay, setReplay] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The parent keys this component by challenge id, so every state above is born fresh for the challenge it
  // belongs to: nothing (reveal, execution, loading, error) is carried from one challenge to the next, and a
  // response that arrives after this instance is gone is dropped by `alive`.
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    let current = true;
    setError(null);
    api
      .labChallenge(id, reveal)
      .then((data) => current && setChallenge(data))
      .catch((e) => current && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      current = false;
    };
  }, [id, reveal]);

  const run = useCallback(
    async (seeds: number[], withReplay: boolean) => {
      setBusy(true);
      setError(null);
      try {
        const result = await api.labExecute(id, seeds, withReplay, reveal);
        if (alive.current) setExecution(result);
      } catch (e) {
        if (alive.current) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (alive.current) setBusy(false);
      }
    },
    [id, reveal],
  );

  const open = useCallback(
    async (seed: number) => {
      setBusy(true);
      setError(null);
      try {
        const opened = await api.labOpen(id, seed);
        if (alive.current) onOpenRun(opened.run.id);
      } catch (e) {
        if (alive.current) {
          setError(e instanceof Error ? e.message : String(e));
          setBusy(false);
        }
      }
    },
    [id, onOpenRun],
  );

  if (!challenge) return <section className="lab-detail">{error ? <div className="banner error">{error}</div> : <p className="muted">Loading...</p>}</section>;

  const playable = challenge.kind === "playable";
  const stored = challenge.stored && "aggregate" in challenge.stored ? challenge.stored : null;
  const storedReasoning = challenge.stored && "result" in challenge.stored ? challenge.stored : null;
  const parsed = parseSeeds(seedText);
  // Shown only for a reveal asked for on this page, even if a response were to carry more.
  const truth = reveal ? challenge.ground_truth : undefined;

  return (
    <section className="lab-detail" data-testid="lab-detail" aria-label={`Challenge ${challenge.id}`}>
      <header className="lab-detail-head">
        <h2>
          <code>{challenge.id}</code> <Chip tone="neutral">{playable ? "playable" : "reasoning only"}</Chip>
        </h2>
        <button onClick={onClose}>Close</button>
      </header>
      {error && <div className="banner error">{error}</div>}
      <p className="small muted">
        Category <b>{challenge.category}</b>: {challenge.category_meaning}
      </p>

      <Section
        title="Ground truth"
        aside={
          <button data-testid="lab-reveal" onClick={() => setReveal(!reveal)}>
            {reveal ? "Hide the ground truth" : "Reveal the ground truth"}
          </button>
        }
      >
        {truth ? (
          <div data-testid="lab-ground-truth" className="lab-truth">
            <p>
              Who the challenge was written around: <b data-testid="lab-culprit">{truth.culprit}</b>
            </p>
            <p>{truth.question}</p>
            {truth.variant_summary && <p className="small">{truth.variant_summary}</p>}
            {truth.prediction && (
              <p className="small">
                <b>Predicted beforehand:</b> {truth.prediction}
              </p>
            )}
            {truth.edits && truth.edits.length > 0 && (
              <details>
                <summary>{truth.edits.length} edits to the base case</summary>
                <ol className="small">
                  {truth.edits.map((edit, i) => (
                    <li key={i}>
                      <code>{edit.op}</code> {edit.target}: {edit.why}
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </div>
        ) : (
          <p className="small muted" data-testid="lab-truth-hidden">
            Hidden: who it was written around, the edits that make it, who was accused and the prose of each expectation. Revealing it is a choice for this page only; opening the challenge as a run keeps the run's own rules for showing the solution.
          </p>
        )}
      </Section>

      {playable && challenge.setup && (
        <Section title="Configuration">
          <table className="table">
            <tbody>
              <tr>
                <td>Scenario</td>
                <td>
                  <code>{challenge.setup.scenario_id}</code> {challenge.setup.scenario_version} (hash {challenge.setup.scenario_hash}), from{" "}
                  <code>{challenge.setup.base}</code>
                </td>
              </tr>
              <tr>
                <td>Policies</td>
                <td>
                  {Object.keys(challenge.setup.policies).length
                    ? Object.entries(challenge.setup.policies).map(([agent, policy]) => <Chip key={agent} tone="agent">{`${agent}: ${policy}`}</Chip>)
                    : "every agent on the baseline policy"}
                </td>
              </tr>
              {challenge.setup.interventions.length > 0 && (
                <tr>
                  <td>Interventions</td>
                  <td>{challenge.setup.interventions.map(([name, tick]) => `${name} after tick ${tick}`).join(", ")}</td>
                </tr>
              )}
              {challenge.setup.solvable && (
                <tr>
                  <td>Solvable by</td>
                  <td>{Object.entries(challenge.setup.solvable).map(([agent, how]) => `${agent}: ${String(how)}`).join(", ")}</td>
                </tr>
              )}
            </tbody>
          </table>
        </Section>
      )}

      {challenge.items && (
        <Section title="Items handed to the reasoner">
          <table className="table">
            <thead>
              <tr>
                <th>Item</th>
                <th>Kind</th>
                <th>From</th>
                <th>Asserts</th>
              </tr>
            </thead>
            <tbody>
              {challenge.items.map((item) => (
                <tr key={item.id}>
                  <td>{item.id}</td>
                  <td>{item.kind}</td>
                  <td>{item.speaker ?? "a record"}{item.origin ? ` (passing on ${item.origin})` : ""}</td>
                  <td>
                    <code>{item.asserts.join(", ")}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      <Section title="Stored result" aside={<Chip tone="neutral">stored</Chip>}>
        {stored ? (
          <div data-testid="lab-stored">
            <p className="small muted">
              The recorded collection, read from disk: {stored.aggregate.runs} runs, replay verified in {stored.aggregate.replay.passed} of {stored.aggregate.replay.verified}. Not recomputed by this page.
            </p>
            <OutcomeBar aggregate={stored.aggregate} />
            <Legend />
            {reveal && stored.aggregate.accused && (
              <p className="small" data-testid="lab-accused">
                Accused: {Object.entries(stored.aggregate.accused).map(([who, count]) => `${who} ${count}`).join(", ")}
              </p>
            )}
            <Measures a={stored.aggregate} />
            <h4>Expectations and predictions</h4>
            <Expectations items={stored.aggregate.expectations} reveal={reveal} />
            <h4>Every recorded seed</h4>
            <RunTable runs={stored.runs} reveal={reveal} busy={busy} onReplay={challenge.can_execute ? (seed) => void run([seed], true) : undefined} onOpen={(seed) => void open(seed)} />
          </div>
        ) : storedReasoning ? (
          <div data-testid="lab-stored">
            <ReasoningResult result={storedReasoning.result} />
            {reveal && (
              <p className="small" data-testid="lab-accused">
                Convicted: {storedReasoning.result.convicted ?? "nobody"}. Prime suspect: {storedReasoning.result.prime_suspect ?? "nobody"}.
              </p>
            )}
            <h4>Expectations and predictions</h4>
            <Expectations items={storedReasoning.expectations} reveal={reveal} />
          </div>
        ) : (
          <Empty>{challenge.stored_problem ?? "No recorded result for this challenge."}</Empty>
        )}
      </Section>

      <Section title={playable ? "Run it again here" : "Run it again"} aside={<Chip tone="neutral">executed on request</Chip>}>
        {!challenge.can_execute ? (
          <p className="small" data-testid="lab-cannot-execute">
            This build is not the one the collection was registered against, so a run now would not be a run of the registered experiment.
          </p>
        ) : (
          <div className="row lab-exec">
            {playable && (
              <>
                <label className="inline">
                  Seeds
                  <input value={seedText} onChange={(e) => setSeedText(e.target.value)} aria-label="Seeds to run" size={10} data-testid="lab-seeds" />
                </label>
                <label className="inline">
                  <input type="checkbox" checked={replay} onChange={(e) => setReplay(e.target.checked)} /> check all four replay levels
                </label>
              </>
            )}
            <button
              className="primary"
              data-testid="lab-execute"
              disabled={busy || (playable && typeof parsed === "string")}
              onClick={() => void run(typeof parsed === "string" ? [] : parsed, replay)}
            >
              {busy ? "Running..." : playable ? `Run ${typeof parsed === "string" ? "..." : parsed.length} seed${typeof parsed !== "string" && parsed.length === 1 ? "" : "s"} now` : "Run now"}
            </button>
            <span className="small muted">
              Local and deterministic, the registered policies only, no model calls, at most {maxSeeds} seeds from here. Nothing is stored.
            </span>
          </div>
        )}
        {playable && typeof parsed === "string" && <p className="small muted">{parsed}</p>}
        {execution && (
          <div data-testid="lab-executed" className="lab-executed">
            <p>
              <Chip tone="tentative">executed just now</Chip> {execution.replay && <Chip tone="believed">all four replay levels checked</Chip>} {execution.label}
            </p>
            {execution.compared_with_stored && (
              <p className="small" data-testid="lab-compared">
                Compared with the stored result: {execution.compared_with_stored.identical} of {execution.compared_with_stored.compared} identical
                {execution.compared_with_stored.different_seeds.length > 0 && `; different at seeds ${execution.compared_with_stored.different_seeds.join(", ")}`}.
              </p>
            )}
            {execution.aggregate && execution.runs && (
              <>
                <OutcomeBar aggregate={execution.aggregate} />
                <RunTable runs={execution.runs} reveal={reveal} busy={busy} onOpen={(seed) => void open(seed)} />
              </>
            )}
            {execution.result && <ReasoningResult result={execution.result} />}
            {execution.expectations && <Expectations items={execution.expectations} reveal={reveal} />}
          </div>
        )}
      </Section>
    </section>
  );
}

export default function CounterfactualLab({ onBack, onOpenRun }: { onBack: () => void; onOpenRun: (runId: string) => void | Promise<void> }) {
  const [overview, setOverview] = useState<LabOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(() => {
    const match = /^#lab\/(.+)$/.exec(window.location.hash);
    return match ? decodeURIComponent(match[1]) : null;
  });

  useEffect(() => {
    api.lab().then(setOverview).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    window.history.replaceState(null, "", selected ? `#lab/${encodeURIComponent(selected)}` : "#lab");
  }, [selected]);

  if (!overview) {
    return (
      <div className="app">
        <div className="welcome">
          <button onClick={onBack}>Back to the investigations</button>
          {error ? <div className="banner error">{error}</div> : <p className="muted">Loading the laboratory...</p>}
        </div>
      </div>
    );
  }

  const stored = overview.stored;
  return (
    <div className="app">
      <div className="lab-page" data-testid="lab-overview">
        <header className="lab-head">
          <button onClick={onBack} data-testid="lab-back">
            Back to the investigations
          </button>
          <h1>{overview.title}</h1>
        </header>

        <div className="banner stale" role="note" data-testid="lab-label">
          <span>
            <b>{overview.label}</b> {overview.notes.map((n) => <span key={n}>{" "}{n}</span>)}
          </span>
        </div>

        <div className="lab-status" data-testid="lab-status">
          {stored.available ? (
            <p>
              <Chip tone="neutral">stored</Chip> The figures below are the recorded collection ({stored.runs} playable runs over seeds {stored.seeds?.[0]} to {stored.seeds?.[1]}, replay checked in {stored.replay_passed} of them), read from <code>{stored.source}</code>. Registered against rules{" "}
              <code>{overview.registered.rules_version}</code>, engine {overview.registered.engine_version}.
            </p>
          ) : (
            <p data-testid="lab-stored-missing">
              <Chip tone="rejected">no stored results</Chip> {stored.problem}
            </p>
          )}
          {overview.drift.length === 0 ? (
            <p className="small muted" data-testid="lab-drift-none">
              This build is the one the collection was registered against, so a bounded re-run here is a run of the registered experiment.
            </p>
          ) : (
            <div className="banner error" data-testid="lab-drift">
              This build differs from the registration, so re-running is refused:
              <ul>
                {overview.drift.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <Section title="Playable challenges" aside={<span className="small muted">stored · counts of runs, with the number of runs as denominator</span>}>
          <Legend />
          <div className="lab-scroll">
            <table className="table lab-compare" data-testid="lab-compare">
              <thead>
                <tr>
                  <th>Challenge</th>
                  <th>Policies</th>
                  <th>Outcomes (of 40)</th>
                  {CATEGORIES.map((c) => (
                    <th key={c} className="num" title={CATEGORY_NOTE[c]}>
                      {CATEGORY_LABEL[c]}
                    </th>
                  ))}
                  <th className="num" title="Median ticks over every run">Median ticks</th>
                  <th className="num" title="Median ticks over runs that ended in a correct accusation">When solved</th>
                  <th className="num" title="False statements ever accepted by a listener / statements made">False accepted</th>
                  <th className="num" title="False statements not rejected by the close">Unrefuted</th>
                  <th className="num" title="Times an agent changed its view of a speaker">Credibility revisions</th>
                  <th className="num">Replay</th>
                </tr>
              </thead>
              <tbody>
                {overview.playable.map((c) => (
                  <tr key={c.id} className={selected === c.id ? "prime" : ""} data-testid={`lab-row-${c.id}`}>
                    <td>
                      <button className="link" onClick={() => setSelected(c.id)} data-testid={`lab-select-${c.id}`}>
                        {c.id}
                      </button>
                      <div className="small muted">{c.category.replace("_", " ")}</div>
                    </td>
                    <td className="small">{Object.entries(c.policies).map(([a, p]) => `${a}: ${p}`).join(", ") || "baseline"}</td>
                    {c.aggregate ? (
                      <>
                        <td className="lab-barcell">
                          <OutcomeBar aggregate={c.aggregate} />
                        </td>
                        {CATEGORIES.map((cat) => (
                          <td key={cat} className="num">
                            {c.aggregate!.categories[cat]}/{c.aggregate!.runs}
                          </td>
                        ))}
                        <td className="num">{num(c.aggregate.median_ticks)}</td>
                        <td className="num">{num(c.aggregate.median_ticks_when_solved)}</td>
                        <td className="num">
                          {c.aggregate.false_ever_accepted}/{c.aggregate.statements}
                        </td>
                        <td className="num">{c.aggregate.false_unrefuted_at_close}</td>
                        <td className="num">{c.aggregate.credibility_revisions}</td>
                        <td className="num">
                          {c.aggregate.replay.passed}/{c.aggregate.replay.verified}
                        </td>
                      </>
                    ) : (
                      <td colSpan={11} className="muted">
                        no stored result
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted">
            Support is a property of the rules' standard of proof, not of the world: a "wrong, supported" outcome is one where the standard was met and the accusation was still wrong. Medians are of whole numbers of ticks.
          </p>
        </Section>

        <Section title="Predictions, and where they were wrong" aside={<Chip tone="neutral">stored</Chip>}>
          <table className="table" data-testid="lab-predictions">
            <tbody>
              <tr>
                <td>Playable challenges</td>
                <td className="num">
                  {overview.predictions.playable.right}/{overview.predictions.playable.of} predictions right
                </td>
              </tr>
              <tr>
                <td>Reasoning-only fixtures</td>
                <td className="num">
                  {overview.predictions.reasoning.right}/{overview.predictions.reasoning.of} predictions right
                </td>
              </tr>
            </tbody>
          </table>
          <p className="small muted">The two kinds are counted separately because they are different experiments. A right prediction means the recorded result matched what was written beforehand; it says nothing about the reasoner being right.</p>
          {overview.wrong_predictions.length > 0 && (
            <table className="table" data-testid="lab-wrong">
              <thead>
                <tr>
                  <th>Challenge</th>
                  <th>Expectation</th>
                  <th>Predicted</th>
                  <th>Observed</th>
                  <th className="num">Held</th>
                </tr>
              </thead>
              <tbody>
                {overview.wrong_predictions.map((w) => (
                  <tr key={`${w.challenge}/${w.expectation}`} className="differs">
                    <td>
                      <button className="link" onClick={() => setSelected(w.challenge)}>
                        {w.challenge}
                      </button>
                    </td>
                    <td>
                      <code>{w.expectation}</code> ({w.kind})
                    </td>
                    <td>{w.predicted}</td>
                    <td>{w.observed.replace("_", " ")}</td>
                    <td className="num">
                      {w.held}/{w.of}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>

        <Section title="Reasoning-only fixtures" aside={<span className="small muted">stored · one set of items, no investigation</span>}>
          <table className="table" data-testid="lab-reasoning">
            <thead>
              <tr>
                <th>Fixture</th>
                <th>Category</th>
                <th>Outcome</th>
                <th>Verdict</th>
              </tr>
            </thead>
            <tbody>
              {overview.reasoning.map((c) => (
                <tr key={c.id} className={selected === c.id ? "prime" : ""} data-testid={`lab-row-${c.id}`}>
                  <td>
                    <button className="link" onClick={() => setSelected(c.id)} data-testid={`lab-select-${c.id}`}>
                      {c.id}
                    </button>
                  </td>
                  <td>{c.category.replace("_", " ")}</td>
                  <td>{c.result ? CATEGORY_LABEL[c.result.category] : "no stored result"}</td>
                  <td>{c.result ? c.result.verdict.replace("_", " ") : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>

        <Section title="Known limitations of the frozen rules">
          <ul className="lab-limits" data-testid="lab-limits">
            {overview.limitations.map((l) => (
              <li key={l.id}>
                <b>{l.id}.</b> {l.explanation}
              </li>
            ))}
          </ul>
          <p className="small muted">Six challenge cases are recorded as strict expected failures for these reasons; the rules were not tuned to make them pass.</p>
        </Section>

        {selected && <Detail key={selected} id={selected} maxSeeds={overview.execute.max_seeds} onClose={() => setSelected(null)} onOpenRun={(id) => void onOpenRun(id)} />}
      </div>
    </div>
  );
}
