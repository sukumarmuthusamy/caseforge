import { useState } from "react";
import type { AgentSnap, Belief, EventRow, Snapshot } from "../api";
import { Chip, Empty, EvidenceRef, GROUNDS_TEXT, Section, StanceTrail, StatusChip } from "./ui";
import type { NameOf } from "./ui";

interface Props {
  agent: AgentSnap;
  snapshot: Snapshot;
  events: EventRow[];
  nameOf: NameOf;
  policies: Record<string, string>;
  canEdit: boolean;
  onSetPolicy: (agent: string, policy: string) => void;
  onSelectNode: (nodeId: string) => void;
  onViewAs: (agent: string) => void;
}

type Tab = "beliefs" | "evidence" | "decisions" | "requests" | "testimony";

function describeAction(action: Record<string, any>): string {
  const { type, ...rest } = action;
  const parts = Object.entries(rest)
    .filter(([, value]) => value !== null && !(Array.isArray(value) && value.length === 0))
    .map(([key, value]) => `${key}=${Array.isArray(value) ? value.join(",") : value}`);
  return parts.length ? `${type}(${parts.join(", ")})` : String(type);
}

function BeliefRow({ belief, texts, onSelectNode }: { belief: Belief; texts: Record<string, string>; onSelectNode: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="belief">
      <button className="belief-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <StatusChip status={belief.status} />
        <span className="belief-text">{belief.text}</span>
        <span className="weights" title="Weight of evidence for and against">
          <b className="pos">+{belief.support}</b> <b className="neg">-{belief.contra}</b>
        </span>
      </button>
      {open && (
        <div className="belief-body">
          <div>
            <span className="k">Supported by</span>
            {belief.evidence.length ? belief.evidence.map((id) => <EvidenceRef key={id} id={id} onSelect={onSelectNode} />) : <span className="muted">no direct evidence</span>}
          </div>
          {belief.against.length > 0 && (
            <div>
              <span className="k">Contradicted by</span>
              {belief.against.map((id) => (
                <EvidenceRef key={id} id={id} onSelect={onSelectNode} />
              ))}
            </div>
          )}
          {belief.derivations.map((d, index) => (
            <div key={index} className={d.active ? "" : "defeated"}>
              <span className="k">Rule {d.rule}</span>
              from {d.premises.map((p) => `"${texts[p] ?? p}"`).join(" and ")}
              {!d.active && d.defeated_by && <em> (defeated: {texts[d.defeated_by] ?? d.defeated_by})</em>}
            </div>
          ))}
          <button className="link" onClick={() => onSelectNode(`prop:${belief.key}`)}>
            Show in graph
          </button>
        </div>
      )}
    </li>
  );
}

export default function AgentPanel({ agent, snapshot, events, nameOf, policies, canEdit, onSetPolicy, onSelectNode, onViewAs }: Props) {
  const [tab, setTab] = useState<Tab>("beliefs");
  const decisions = events.filter((e) => (e.type === "ActionTaken" || e.type === "ActionRejected") && e.data.agent === agent.id).reverse();
  const requests = snapshot.requests.filter((r) => r.sender === agent.id || r.recipient === agent.id);
  const statements = snapshot.statements.filter((s) => s.speaker === agent.id || s.recipient === agent.id);
  const suspects = snapshot.case.suspects;

  return (
    <div className="agent-panel">
      <header className="agent-head">
        <div>
          <h2>{agent.name}</h2>
          <div className="muted">
            {agent.role} · {agent.actions} actions{agent.rejected ? `, ${agent.rejected} rejected` : ""}
          </div>
        </div>
        <div className="agent-head-controls">
          <label className="inline">
            Policy
            <select value={agent.policy} disabled={!canEdit} onChange={(e) => onSetPolicy(agent.id, e.target.value)} title={policies[agent.policy]}>
              {Object.keys(policies).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <button onClick={() => onViewAs(agent.id)} title="Show the graph as this agent sees it">
            Graph as {agent.name.split(" ").slice(-1)[0]}
          </button>
        </div>
      </header>
      <ul className="goals">
        {agent.goals.map((goal) => (
          <li key={goal}>{goal}</li>
        ))}
      </ul>

      {snapshot.agendas?.[agent.id] && (
        <div className="callout callout-warn" data-testid="agenda">
          <b>Private agenda</b> <span className="muted">(shown because the solution is revealed)</span>
          <div>
            Keeps {nameOf(snapshot.agendas[agent.id].protects)} out of the record
            {snapshot.agendas[agent.id].deflects_to && (
              <>
                {" "}
                and steers suspicion towards {nameOf(snapshot.agendas[agent.id].deflects_to)}
                {snapshot.agendas[agent.id].leaks_to && <> through {nameOf(snapshot.agendas[agent.id].leaks_to)}</>}
              </>
            )}
            .
          </div>
          <div className="muted">{snapshot.agendas[agent.id].note}</div>
          <div className="muted">{agent.policy === "deceptive" ? "This agent is acting on it." : `Not acted on: this agent runs the ${agent.policy} policy.`}</div>
        </div>
      )}
      {agent.discrepancies.length > 0 && (
        <div className="callout callout-warn" data-testid="discrepancies">
          <b>Caught withholding</b>
          {agent.discrepancies.map((d) => (
            <div key={`${d.request}-${d.evidence}`}>
              Tick {d.tick}: {nameOf(d.against)}'s answer to {d.request} left out <EvidenceRef id={d.evidence} onSelect={onSelectNode} />
            </div>
          ))}
          {agent.escalated.length > 0 && <div className="muted">Took direct access to the sources of {agent.escalated.map((id) => nameOf(id)).join(", ")}.</div>}
        </div>
      )}

      {agent.credibility.length > 0 && (
        <div className="callout" data-testid="credibility">
          <b>Whose word {agent.name.split(" ").slice(-1)[0]} could check</b>{" "}
          <span className="muted">(against the records this agent holds, nothing else)</span>
          {agent.credibility.map((c) => (
            <div key={c.speaker} data-testid={`credibility-${c.speaker}`}>
              <Chip tone={c.standing === "impeached" ? "rejected" : "believed"} title={c.history.map((h) => `tick ${h.tick}: ${h.standing ?? "nothing left to check"}`).join("\n")}>
                {c.standing === "impeached" ? "caught out" : "borne out"}
              </Chip>{" "}
              <b>{c.name}</b>
              {c.refuted.length > 0 && <span> · evidence contradicts: {c.refuted.map((p) => `"${p.text}"`).join("; ")}</span>}
              {c.corroborated.length > 0 && <span className="muted"> · evidence supports: {c.corroborated.map((p) => `"${p.text}"`).join("; ")}</span>}
            </div>
          ))}
          <div className="muted small">Someone caught out once is no longer believed on their word alone. Being borne out earns no extra weight.</div>
        </div>
      )}

      <Section title="Suspect assessment" aside={<span className="muted">prime: {agent.prime_suspect ? nameOf(agent.prime_suspect) : "nobody"}</span>}>
        <table className="table">
          <thead>
            <tr>
              <th>Suspect</th>
              <th title="Opportunity">Opp.</th>
              <th>Means</th>
              <th>Motive</th>
              <th title="Named by hearsay">Named</th>
              <th className="num">Score</th>
            </tr>
          </thead>
          <tbody>
            {suspects.map((id) => {
              const a = agent.suspects[id];
              return (
                <tr key={id} className={agent.prime_suspect === id ? "prime" : ""}>
                  <td>
                    <button className="link" onClick={() => onSelectNode(`ent:${id}`)}>
                      {nameOf(id)}
                    </button>
                  </td>
                  <td>{a ? <Chip tone={`opp-${a.opportunity}`}>{a.opportunity}</Chip> : "-"}</td>
                  <td>{a?.means ? "yes" : "-"}</td>
                  <td>{a && a.motive !== "none" ? a.motive : "-"}</td>
                  <td>{a?.named ? `+${a.named}` : "-"}</td>
                  <td className="num">{a?.score ?? 0}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Section>

      <nav className="tabs" role="tablist">
        {(
          [
            ["beliefs", `Beliefs ${agent.beliefs.length}`],
            ["evidence", `Evidence ${agent.holdings.length}`],
            ["decisions", `Decisions ${decisions.length}`],
            ["requests", `Requests ${requests.length}`],
            ["testimony", `Said ${statements.length}`],
          ] as [Tab, string][]
        ).map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </nav>

      {tab === "beliefs" && (
        <>
          {agent.contradictions.length > 0 && (
            <div className="callout">
              <b>Contradictions recognized</b>
              {agent.contradictions.map((c) => (
                <div key={c.pair}>
                  "{c.a}" <span className="vs">vs</span> "{c.b}"
                </div>
              ))}
            </div>
          )}
          {agent.beliefs.length === 0 ? (
            <Empty>No beliefs yet. This agent has not learned anything.</Empty>
          ) : (
            <ul className="beliefs">
              {agent.beliefs.map((belief) => (
                <BeliefRow key={belief.key} belief={belief} texts={snapshot.propositions} onSelectNode={onSelectNode} />
              ))}
            </ul>
          )}
        </>
      )}

      {tab === "evidence" && (
        <>
          {agent.holdings.length === 0 && <Empty>Holds no evidence.</Empty>}
          <ul className="cards">
            {agent.holdings.map((holding) => {
              const evidence = snapshot.evidence[holding.id];
              if (!evidence) return null;
              return (
                <li key={holding.id} className="card">
                  <div className="card-head">
                    <EvidenceRef id={holding.id} onSelect={onSelectNode} />
                    <b>{evidence.title}</b>
                    <Chip tone={`kind-${evidence.kind}`}>{evidence.kind}</Chip>
                  </div>
                  <p>{evidence.text}</p>
                  <div className="muted small">
                    Tick {holding.tick} ·{" "}
                    {holding.via === "shared"
                      ? `received from ${nameOf(holding.from_agent)}`
                      : holding.via === "released"
                        ? "delivered by an intervention"
                        : holding.via === "initial"
                          ? "held from the start"
                          : `found in ${evidence.source_name}`}
                    {holding.chain.length > 1 && ` · custody: ${holding.chain.map((id) => nameOf(id)).join(" → ")}`}
                  </div>
                </li>
              );
            })}
          </ul>
          <div className="muted small">
            Can reach:{" "}
            {agent.sources.map((s) => `${s.name}${s.mode === "request" ? " (by request)" : ""}`).join(", ") || "nothing"}
          </div>
        </>
      )}

      {tab === "decisions" && (
        <>
          {decisions.length === 0 && <Empty>No decisions yet.</Empty>}
          <ul className="cards">
            {decisions.map((event) => {
              const trace = event.data.trace ?? {};
              const considered: any[] = trace.considered ?? [];
              return (
                <li key={event.seq} className={`card ${event.type === "ActionRejected" ? "card-bad" : ""}`}>
                  <div className="card-head">
                    <span className="tick">t{event.tick}</span>
                    <code>{describeAction(event.data.action)}</code>
                    {event.type === "ActionRejected" && <Chip tone="rejected">rejected: {event.data.code}</Chip>}
                  </div>
                  <p>{trace.reason}</p>
                  {event.type === "ActionRejected" && <p className="neg">{event.data.message}</p>}
                  {trace.refs?.length > 0 && (
                    <div className="small">
                      <span className="k">Rested on</span>
                      {trace.refs.map((id: string) => (id.startsWith("R") ? <span key={id} className="ref static">{id}</span> : <EvidenceRef key={id} id={id} onSelect={onSelectNode} />))}
                    </div>
                  )}
                  {trace.llm && (
                    <div className="small muted">
                      Model {trace.llm.model} · {trace.llm.fallback ? "fell back to baseline" : `chose menu item ${trace.llm.choice}`} · {trace.llm.attempts?.length ?? 0} attempt(s)
                    </div>
                  )}
                  {considered.length > 1 && (
                    <details>
                      <summary>Alternatives considered ({considered.length})</summary>
                      <table className="table small">
                        <tbody>
                          {considered.map((option, index) => (
                            <tr key={index}>
                              <td className="num">{option.priority}</td>
                              <td>
                                <code>{describeAction(option.action)}</code>
                                <div className="muted">{option.why}</div>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </details>
                  )}
                  <div className="muted small">
                    policy: {trace.policy} · event #{event.seq}
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}

      {tab === "testimony" && (
        <>
          {agent.observations.length > 0 && (
            <div className="callout" data-testid="observations">
              <b>Saw for itself</b>
              {agent.observations.map((o) => (
                <div key={o.id}>
                  <span className="ref static">{o.id}</span>{" "}
                  <button className="link" onClick={() => onSelectNode(`prop:${o.key}`)}>
                    {o.text}
                  </button>
                </div>
              ))}
            </div>
          )}
          {statements.length === 0 && <Empty>Nothing said to or by this agent.</Empty>}
          <ul className="cards">
            {[...statements].reverse().map((s) => {
              const mine = s.speaker === agent.id;
              return (
                <li key={s.id} className="card" data-testid="statement">
                  <div className="card-head">
                    <span className="tick">t{s.tick}</span>
                    <EvidenceRef id={s.id} onSelect={onSelectNode} />
                    <b>
                      {nameOf(s.speaker)} → {nameOf(s.recipient)}
                    </b>
                    {s.origin && <Chip tone="kind-hearsay">passing on {nameOf(s.origin)}</Chip>}
                  </div>
                  <p>"{s.text}"</p>
                  <div className="small">
                    <span className="k">{nameOf(s.recipient)} makes of it</span>
                    <StanceTrail stances={s.stances} />
                  </div>
                  <div
                    className={`small ${s.grounds === "none" ? "neg" : "muted"}`}
                    data-testid="grounds"
                    title={`${nameOf(s.speaker)} knows this. ${nameOf(s.recipient)} was told only the statement.`}
                  >
                    <span className="k">{mine ? "This agent" : nameOf(s.speaker)}</span>{" "}
                    {s.origin ? `was told so by ${nameOf(s.origin)}` : GROUNDS_TEXT[s.grounds]}
                    {s.grounds === "held" && s.backing.map((id) => <EvidenceRef key={id} id={id} onSelect={onSelectNode} />)}
                  </div>
                </li>
              );
            })}
          </ul>
          <p className="muted small">A statement is one person's word. It is weighed, not verified, and whether it was true is not shown while the case is open.</p>
        </>
      )}

      {tab === "requests" && (
        <>
          {requests.length === 0 && <Empty>No requests sent or received.</Empty>}
          <ul className="cards">
            {[...requests].reverse().map((request) => (
              <li key={request.id} className="card">
                <div className="card-head">
                  <span className="tick">t{request.tick}</span>
                  <b>
                    {nameOf(request.sender)} → {nameOf(request.recipient)}
                  </b>
                  <Chip tone={`req-${request.status}`}>{request.status.replace("_", " ")}</Chip>
                </div>
                <p>
                  {request.source_name ? `Search ${request.source_name} for ` : "What do you know about "}
                  {nameOf(request.topic)}
                  {request.source_name ? "" : "?"}
                </p>
                {request.evidence.length > 0 && (
                  <div className="small">
                    <span className="k">Delivered</span>
                    {request.evidence.map((id) => (
                      <EvidenceRef key={id} id={id} onSelect={onSelectNode} />
                    ))}
                  </div>
                )}
                {request.withheld.length > 0 && (
                  <div className="small neg" data-testid="withheld" title={`${nameOf(request.recipient)} knows this. ${nameOf(request.sender)} was only told what was delivered.`}>
                    <span className="k">Held back by {nameOf(request.recipient)}</span>
                    {request.withheld.map((id) => (
                      <EvidenceRef key={id} id={id} onSelect={onSelectNode} />
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
