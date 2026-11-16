import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { Comparison, Evaluation, EventRow, GraphData, RunSummary, ScenarioSummary, Snapshot, VerifyReport } from "./api";
import AgentPanel from "./components/AgentPanel";
import CounterfactualLab from "./components/CounterfactualLab";
import DetailPanel from "./components/DetailPanel";
import EvaluationPanel from "./components/EvaluationPanel";
import GraphPanel from "./components/GraphPanel";
import LabPanel from "./components/LabPanel";
import Timeline from "./components/Timeline";
import { Chip, Empty, shortHash } from "./components/ui";

type RightTab = "agent" | "selection" | "lab" | "evaluation";

const PLAY_INTERVAL_MS = 700;

function labFromHash(): boolean {
  return window.location.hash.startsWith("#lab");
}

function runFromHash(): string | null {
  const match = window.location.hash.match(/run=([0-9a-f]+)/);
  return match ? match[1] : null;
}

function NewRunDialog({ scenarios, onCreate, onClose, busy }: { scenarios: ScenarioSummary[]; onCreate: (body: { scenario_id: string; seed: number; policies: Record<string, string>; label: string }) => void; onClose: () => void; busy: boolean }) {
  const [scenarioId, setScenarioId] = useState(scenarios[0]?.id ?? "");
  const [seed, setSeed] = useState(7);
  const [label, setLabel] = useState("");
  const [policies, setPolicies] = useState<Record<string, string>>({});
  const scenario = scenarios.find((s) => s.id === scenarioId);
  if (!scenario) return null;
  return (
    <div className="modal-back" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="New investigation" onClick={(e) => e.stopPropagation()}>
        <h2>New investigation</h2>
        <p className="quote">{scenario.briefing}</p>
        <div className="form">
          <label>
            Scenario
            <select
              value={scenarioId}
              onChange={(e) => {
                setScenarioId(e.target.value);
                setPolicies({}); // the choices belong to the other case's agents
              }}
            >
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.title} (v{s.version})
                </option>
              ))}
            </select>
          </label>
          <label>
            Seed
            <span className="row">
              <input type="number" min={0} max={2147483647} value={seed} onChange={(e) => setSeed(Math.max(0, Math.floor(Number(e.target.value) || 0)))} />
              <button type="button" onClick={() => setSeed(Math.floor(Math.random() * 100000))}>
                Random
              </button>
            </span>
            <span className="muted small">The same seed and the same interventions always produce the same investigation.</span>
          </label>
          <label>
            Label
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Optional name for this run" maxLength={80} />
          </label>
          <fieldset>
            <legend>Agent policies</legend>
            {scenario.agents.map((agent) => (
              <label key={agent.id} className="policy-row">
                <span>
                  {agent.name} <span className="muted">({agent.role})</span>
                </span>
                <select value={policies[agent.id] ?? "baseline"} onChange={(e) => setPolicies({ ...policies, [agent.id]: e.target.value })}>
                  {Object.keys(scenario.policies).map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            ))}
            <ul className="plain small muted">
              {Object.entries(scenario.policies).map(([name, text]) => (
                <li key={name}>
                  <b>{name}</b>: {text}
                </li>
              ))}
            </ul>
          </fieldset>
        </div>
        <div className="modal-actions">
          <button onClick={onClose}>Cancel</button>
          <button className="primary" disabled={busy} onClick={() => onCreate({ scenario_id: scenarioId, seed, policies, label })}>
            Open the case
          </button>
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runId, setRunId] = useState<string | null>(runFromHash());
  const [viewTick, setViewTick] = useState<number | null>(null); // null follows the latest tick
  const [perspective, setPerspective] = useState("all");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [events, setEvents] = useState<EventRow[]>([]);
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [verify, setVerify] = useState<VerifyReport | null>(null);
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [tab, setTab] = useState<RightTab>("agent");
  const [busy, setBusy] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [labOpen, setLabOpen] = useState(labFromHash()); // the counterfactual laboratory replaces the investigation screens
  const [version, setVersion] = useState(0); // bumped after every mutation to trigger a reload
  const requestToken = useRef(0);

  const fail = useCallback((e: unknown) => setError(e instanceof Error ? e.message : String(e)), []);

  const loadRuns = useCallback(async () => {
    const list = await api.runs();
    setRuns(list);
    return list;
  }, []);

  // Initial load: scenarios and existing runs.
  useEffect(() => {
    (async () => {
      try {
        const [scenarioList, runList] = await Promise.all([api.scenarios(), loadRuns()]);
        setScenarios(scenarioList);
        const usable = runList.filter((r) => r.compatible);
        setRunId((current) => (current && usable.some((r) => r.id === current) ? current : usable[0]?.id ?? null));
      } catch (e) {
        fail(e);
      } finally {
        setLoaded(true);
      }
    })();
  }, [loadRuns, fail]);

  // Everything shown for the current run, tick and perspective comes from the server.
  useEffect(() => {
    if (!runId) {
      setSnapshot(null);
      setGraph(null);
      setEvents([]);
      setEvaluation(null);
      return;
    }
    if (!labOpen) window.history.replaceState(null, "", `#run=${runId}`);
    const token = ++requestToken.current;
    (async () => {
      try {
        const [snap, graphData, eventRows, evalData] = await Promise.all([
          api.snapshot(runId, viewTick),
          api.graph(runId, viewTick, perspective),
          api.events(runId),
          api.evaluation(runId),
        ]);
        if (token !== requestToken.current) return; // a newer request superseded this one
        setSnapshot(snap);
        setGraph(graphData);
        setEvents(eventRows);
        setEvaluation(evalData);
      } catch (e) {
        if (token === requestToken.current) fail(e);
      }
    })();
  }, [runId, viewTick, perspective, version, fail, labOpen]);

  // Switching run resets everything tied to the previous one.
  const openRun = useCallback((id: string | null) => {
    setPlaying(false);
    setRunId(id);
    setViewTick(null);
    setPerspective("all");
    setSelectedNode(null);
    setVerify(null);
    setComparison(null);
    setError(null);
  }, []);

  const mutate = useCallback(
    async (operation: () => Promise<unknown>) => {
      setBusy(true);
      setError(null);
      try {
        await operation();
        setVersion((v) => v + 1);
        await loadRuns();
      } catch (e) {
        fail(e);
      } finally {
        setBusy(false);
      }
    },
    [loadRuns, fail],
  );

  // A read that produces a report (verify, compare). It changes nothing on the server,
  // so it does not trigger a reload. Reports are tied to the log they describe instead
  // (see LabPanel), which is what keeps one from being shown against a newer log.
  const read = useCallback(
    async (operation: () => Promise<unknown>) => {
      setBusy(true);
      setError(null);
      try {
        await operation();
      } catch (e) {
        fail(e);
      } finally {
        setBusy(false);
      }
    },
    [fail],
  );

  // Auto-play: one tick at a time so each step is visible.
  useEffect(() => {
    if (!playing || !runId) return;
    let cancelled = false;
    let timer = 0;
    const advance = async () => {
      if (cancelled) return;
      try {
        const result = await api.step(runId, 1);
        if (cancelled) return;
        setVersion((v) => v + 1);
        if (result.run.status !== "running") {
          setPlaying(false);
          loadRuns().catch(fail);
          return;
        }
        timer = window.setTimeout(advance, PLAY_INTERVAL_MS);
      } catch (e) {
        fail(e);
        setPlaying(false);
      }
    };
    timer = window.setTimeout(advance, 150);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [playing, runId, loadRuns, fail]);

  const nameOf = useCallback(
    (id: string | null | undefined) => {
      if (!id) return "nobody";
      if (id === "user") return "the operator";
      if (id === "anonymous") return "an anonymous source";
      return snapshot?.entities[id]?.name ?? id;
    },
    [snapshot],
  );

  const run = snapshot?.run ?? null;
  const agents = snapshot?.agents ?? [];
  const agent = agents.find((a) => a.id === selectedAgent) ?? agents[0] ?? null;
  // Where the user asked the slider to be. It is kept apart from the snapshot that was last
  // loaded: a key pressed while a request is still outstanding must start from the requested
  // position, not from the old data, or the step is lost.
  const requestedTick = viewTick ?? snapshot?.latest_tick ?? 0;

  const visibleEvents = useMemo(() => (snapshot ? events.filter((e) => e.tick <= snapshot.tick) : []), [events, snapshot]);
  // A laboratory variant is `<base>.<variant>`: it offers the same policies as the case it was made from.
  const scenario = scenarios.find((s) => s.id === run?.scenario_id?.split(".")[0]) ?? scenarios[0];
  const readOnly = !!run && !run.continuable;
  const live = !!snapshot && snapshot.is_latest && run?.status === "running" && !readOnly;

  const selectNode = useCallback((nodeId: string | null) => {
    setSelectedNode(nodeId);
    if (nodeId) setTab("selection");
  }, []);

  const selectAgent = useCallback((id: string) => {
    setSelectedAgent(id);
    setTab("agent");
  }, []);

  const step = (ticks: number) => {
    if (!runId) return;
    setViewTick(null);
    void mutate(() => api.step(runId, ticks));
  };

  const createRun = (body: { scenario_id: string; seed: number; policies: Record<string, string>; label: string }) =>
    void mutate(async () => {
      const created = await api.createRun(body);
      setShowNew(false);
      openRun(created.id);
    });

  const deleteStale = (target: RunSummary) => {
    if (!window.confirm(`Delete run ${target.label || target.id}? Its event log will be removed permanently.`)) return;
    void mutate(() => api.deleteRun(target.id));
  };

  // -- screens ---------------------------------------------------------------

  const leaveLab = () => {
    setLabOpen(false);
    window.history.replaceState(null, "", runId ? `#run=${runId}` : "#");
  };

  if (loaded && labOpen) {
    return (
      <CounterfactualLab
        onBack={leaveLab}
        onOpenRun={async (id) => {
          // The challenge was opened as an ordinary run: show it in the investigation screens.
          try {
            await loadRuns();
          } catch (e) {
            fail(e);
          }
          openRun(id);
          setLabOpen(false);
        }}
      />
    );
  }

  if (!loaded) {
    return (
      <div className="app">
        <div className="welcome">
          <h1>CaseForge</h1>
          <p className="muted">Connecting to the investigation server...</p>
        </div>
      </div>
    );
  }

  if (!runId || !snapshot || !run) {
    return (
      <div className="app">
        <div className="welcome">
          <h1>CaseForge</h1>
          <p className="lede">A laboratory for watching agents investigate with incomplete, contradictory information, and for measuring how well they did.</p>
          {error && <div className="banner error">{error}</div>}
          {scenario ? (
            <div className="welcome-card">
              <h2>{scenario.title}</h2>
              <p className="quote">{scenario.briefing}</p>
              <ul className="roster">
                {scenario.agents.map((a) => (
                  <li key={a.id}>
                    <b>{a.name}</b> <span className="muted">{a.role}</span>
                    <div className="small muted">{a.goals[0]}</div>
                  </li>
                ))}
              </ul>
              <div className="row">
                <button className="primary" disabled={busy} onClick={() => createRun({ scenario_id: scenario.id, seed: 7, policies: {}, label: "" })}>
                  Open the case (seed 7)
                </button>
                <button onClick={() => setShowNew(true)}>Choose seed and policies...</button>
                <button onClick={() => setLabOpen(true)} data-testid="lab-open">
                  Counterfactual Lab
                </button>
              </div>
              <p className="muted small">No API key or account is needed. Every agent runs a deterministic policy by default.</p>
            </div>
          ) : (
            !error && <Empty>No scenarios are installed.</Empty>
          )}
          {runs.length > 0 && (
            <div className="welcome-card">
              <h3>Earlier runs</h3>
              <ul className="plain">
                {runs.map((r) =>
                  r.compatible ? (
                    <li key={r.id}>
                      <button className="link" onClick={() => openRun(r.id)}>
                        {r.label || r.id}
                      </button>{" "}
                      <span className="muted">
                        seed {r.seed} · tick {r.tick} · {r.status}
                        {!r.continuable && " · read-only: recorded under other rules"}
                      </span>
                    </li>
                  ) : (
                    <li key={r.id} data-testid="incompatible-run">
                      <b>{r.label || r.id}</b> <span className="muted">seed {r.seed} · cannot be opened: {r.incompatible_reason}</span>{" "}
                      <button className="link" disabled={busy} onClick={() => deleteStale(r)}>
                        Delete
                      </button>
                    </li>
                  ),
                )}
              </ul>
            </div>
          )}
        </div>
        {showNew && <NewRunDialog scenarios={scenarios} busy={busy} onCreate={createRun} onClose={() => setShowNew(false)} />}
      </div>
    );
  }

  const statusTone = run.status === "running" ? "tentative" : run.accused ? "believed" : "disputed";
  const statusText = run.status === "running" ? "open" : run.close_reason === "accusation" ? `closed: ${nameOf(run.accused)} accused` : "closed: tick limit";

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">CF</span>
          <div>
            <div className="brand-name">CaseForge</div>
            <div className="brand-case">{snapshot.case.title}</div>
          </div>
        </div>
        <label className="inline">
          Run
          <select value={run.id} onChange={(e) => openRun(e.target.value)} aria-label="Select run">
            {runs.map((r) => (
              <option key={r.id} value={r.id} disabled={!r.compatible} title={r.incompatible_reason ?? undefined}>
                {r.label || r.id} · seed {r.seed} · {r.compatible ? `t${r.tick} · ${r.status}${r.continuable ? "" : " · read-only"}` : "from another version, cannot be opened"}
              </option>
            ))}
          </select>
        </label>
        <button onClick={() => setShowNew(true)}>New run</button>
        <button onClick={() => setLabOpen(true)} data-testid="lab-open" title="Recorded counterfactual challenges, and small re-runs of them">
          Counterfactual Lab
        </button>
        <Chip tone={statusTone}>{statusText}</Chip>
        <span className="muted small" title={`Head hash ${run.head_hash}`}>
          seed {run.seed} · {run.seq + 1} events · {shortHash(run.head_hash)}
        </span>
        <div className="spacer" />
        <div className="transport">
          <button disabled={busy || playing || !live} onClick={() => step(1)} title="Advance one tick: every agent acts once">
            Step
          </button>
          <button disabled={busy || playing || !live} onClick={() => step(5)}>
            +5
          </button>
          <button
            className={playing ? "on" : ""}
            disabled={busy || run.status !== "running" || readOnly}
            onClick={() => {
              setViewTick(null);
              setPlaying(!playing);
            }}
          >
            {playing ? "Pause" : "Play"}
          </button>
          <button className="primary" disabled={busy || playing || !live} onClick={() => step(100)} title="Run until the case closes">
            Run to end
          </button>
        </div>
      </header>

      <div className="scrubber">
        <span className="scrub-label">
          Tick <b>{snapshot.tick}</b> of {snapshot.latest_tick}
          <span className="muted"> (limit {run.max_ticks})</span>
          {requestedTick !== snapshot.tick && (
            <span className="muted" data-testid="scrub-pending"> loading tick {requestedTick}...</span>
          )}
        </span>
        <input
          type="range"
          min={0}
          max={Math.max(snapshot.latest_tick, 1)}
          value={requestedTick}
          disabled={snapshot.latest_tick === 0 || playing}
          onChange={(e) => {
            const value = Number(e.target.value);
            setViewTick(value >= snapshot.latest_tick ? null : value);
          }}
          aria-label="View tick"
        />
        {snapshot.is_latest ? (
          <span className="muted small">Showing the latest state. Drag to look back in time.</span>
        ) : (
          <>
            <Chip tone="disputed">viewing the past</Chip>
            <button onClick={() => setViewTick(null)}>Back to latest</button>
            <button onClick={() => setTab("lab")} title="Open the lab tab to branch from this tick">
              Branch from here...
            </button>
          </>
        )}
      </div>

      {readOnly && run?.compatibility && (
        <div className="banner stale" role="status" data-testid="readonly-banner">
          <span>
            <Chip tone="disputed">read-only</Chip> {run.compatibility.detail}.
            {run.compatibility.first_divergence !== null && <> Verify shows where it diverges.</>}
          </span>
        </div>
      )}

      {error && (
        <div className="banner error" role="alert">
          <span>{error}</span>
          <button onClick={() => setError(null)}>Dismiss</button>
        </div>
      )}

      <main className="main">
        <aside className="left">
          <div className="panel">
            <header className="panel-head">
              <h2>Case</h2>
            </header>
            <div className="pad">
              <p className="briefing">{snapshot.case.briefing}</p>
              <div className="stat-grid two">
                <div className="stat">
                  <b>
                    {snapshot.progress.evidence_discovered}/{snapshot.progress.evidence_total}
                  </b>
                  <span>evidence found</span>
                </div>
                <div className="stat">
                  <b>{snapshot.progress.contradictions_recognized}</b>
                  <span>contradictions</span>
                </div>
                <div className="stat">
                  <b>{snapshot.claims.filter((c) => c.status === "active").length}</b>
                  <span>active claims</span>
                </div>
                <div className="stat">
                  <b>{snapshot.requests.filter((r) => r.status === "pending").length}</b>
                  <span>pending requests</span>
                </div>
              </div>
              {snapshot.accusation && (
                <div className="callout">
                  <b>{nameOf(snapshot.accusation.by)}</b> accused <b>{nameOf(snapshot.accusation.suspect)}</b> at tick {snapshot.accusation.tick}.{" "}
                  <button className="link" onClick={() => setTab("evaluation")}>
                    See the evaluation
                  </button>
                </div>
              )}
            </div>
          </div>
          <div className="panel grow">
            <header className="panel-head">
              <h2>Agents</h2>
            </header>
            <ul className="agent-list">
              {agents.map((a) => (
                <li key={a.id}>
                  <button className={`agent-card ${agent?.id === a.id && tab === "agent" ? "on" : ""}`} onClick={() => selectAgent(a.id)}>
                    <div className="agent-card-head">
                      <b>{a.name}</b>
                      <span className="muted">{a.role}</span>
                    </div>
                    <div className="agent-card-row">
                      <span>{a.holdings.length} evidence</span>
                      <span>{a.beliefs.filter((b) => b.status === "believed").length} believed</span>
                      {a.contradictions.length > 0 && <span>{a.contradictions.length} contradictions</span>}
                    </div>
                    <div className="agent-card-row">
                      <span className="muted">suspects</span>
                      {a.prime_suspect ? <Chip tone="disputed">{nameOf(a.prime_suspect)}</Chip> : <span className="muted">nobody yet</span>}
                      {a.policy !== "baseline" && <Chip tone="neutral">{a.policy}</Chip>}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </aside>

        <section className="center">
          <GraphPanel graph={graph} selected={selectedNode} onSelect={selectNode} perspective={perspective} onPerspective={setPerspective} agents={agents.map((a) => ({ id: a.id, name: a.name }))} />
          <Timeline events={visibleEvents} focusAgent={agent?.id ?? null} focusAgentName={agent?.name ?? null} onJump={(tick) => setViewTick(tick >= snapshot.latest_tick ? null : tick)} />
        </section>

        <aside className="right panel">
          <nav className="tabs main-tabs" role="tablist">
            {(
              [
                ["agent", "Agent"],
                ["selection", "Selection"],
                ["lab", "Lab"],
                ["evaluation", "Evaluation"],
              ] as [RightTab, string][]
            ).map(([id, text]) => (
              <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>
                {text}
              </button>
            ))}
          </nav>
          <div className="right-body">
            {tab === "agent" &&
              (agent ? (
                <AgentPanel
                  agent={agent}
                  snapshot={snapshot}
                  events={visibleEvents}
                  nameOf={nameOf}
                  policies={Object.fromEntries(Object.entries(scenario?.policies ?? { baseline: "" }))}
                  canEdit={live && !busy && !playing}
                  onSetPolicy={(agentId, policy) => void mutate(() => api.setPolicy(run.id, agentId, policy))}
                  onSelectNode={selectNode}
                  onViewAs={setPerspective}
                />
              ) : (
                <Empty>No agents.</Empty>
              ))}
            {tab === "selection" && <DetailPanel nodeId={selectedNode} graph={graph} snapshot={snapshot} nameOf={nameOf} onSelectNode={selectNode} onSelectAgent={selectAgent} />}
            {tab === "lab" && (
              <LabPanel
                snapshot={snapshot}
                runs={runs}
                busy={busy || playing}
                verify={verify}
                comparison={comparison}
                onIntervene={(id) => void mutate(() => api.intervene(run.id, id))}
                onVerify={() =>
                  void read(async () => {
                    setVerify(await api.verify(run.id));
                  })
                }
                onBranch={(tick, label) =>
                  void mutate(async () => {
                    const branch = await api.branch(run.id, tick, label);
                    openRun(branch.id);
                    setTab("lab");
                  })
                }
                onCompare={(other) =>
                  void read(async () => {
                    setComparison(await api.compare(run.id, other));
                  })
                }
                onOpenRun={openRun}
                onDelete={() => {
                  if (!window.confirm(`Delete run ${run.label || run.id}? Its event log will be removed permanently.`)) return;
                  void mutate(async () => {
                    await api.deleteRun(run.id);
                    const remaining = await api.runs();
                    openRun(remaining.find((r) => r.compatible)?.id ?? null);
                  });
                }}
              />
            )}
            {tab === "evaluation" && <EvaluationPanel evaluation={evaluation} snapshot={snapshot} nameOf={nameOf} busy={busy} onReveal={() => void mutate(() => api.reveal(run.id))} onSelectNode={selectNode} />}
          </div>
        </aside>
      </main>

      {showNew && <NewRunDialog scenarios={scenarios} busy={busy} onCreate={createRun} onClose={() => setShowNew(false)} />}
    </div>
  );
}
