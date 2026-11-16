import { useEffect, useMemo, useRef, useState } from "react";
import type { EventRow } from "../api";
import { Empty } from "./ui";

interface Props {
  events: EventRow[];
  focusAgent: string | null;
  focusAgentName: string | null;
  onJump: (tick: number) => void;
}

type Filter = "key" | "all" | "actions" | "evidence" | "claims" | "beliefs";

const CATEGORY: Record<string, string> = {
  RunStarted: "system",
  TickStarted: "system",
  InterventionApplied: "user",
  AccessGranted: "user",
  PolicyChanged: "user",
  EvidenceReleased: "user",
  ActionTaken: "action",
  ActionRejected: "rejected",
  SourceInspected: "evidence",
  EvidenceObserved: "evidence",
  EvidenceShared: "evidence",
  RequestSent: "talk",
  RequestAnswered: "talk",
  EvidenceWithheld: "deception",
  DiscrepancyNoticed: "deception",
  AccessEscalated: "deception",
  ClaimPublished: "claim",
  ClaimRetracted: "claim",
  BeliefsRevised: "belief",
  ContradictionRecognized: "contradiction",
  StatementMade: "talk",
  StatementWeighed: "belief",
  CredibilityRevised: "deception",
  AccusationMade: "verdict",
  CaseClosed: "verdict",
};

const FILTERS: { id: Filter; label: string; hint: string }[] = [
  { id: "key", label: "Key events", hint: "Hides waits, duplicate bookkeeping and belief updates that did not change a prime suspect" },
  { id: "all", label: "All", hint: "Every event in the log" },
  { id: "actions", label: "Actions", hint: "What agents chose to do" },
  { id: "evidence", label: "Evidence", hint: "Searches, discoveries and hand-overs" },
  { id: "claims", label: "Claims", hint: "Requests, public claims and retractions" },
  { id: "beliefs", label: "Beliefs", hint: "Belief revisions and contradictions" },
];

function keep(event: EventRow, filter: Filter): boolean {
  const category = CATEGORY[event.type] ?? "system";
  switch (filter) {
    case "all":
      return event.type !== "TickStarted";
    case "actions":
      return category === "action" || category === "rejected" || category === "verdict" || category === "user" || event.type === "AccessEscalated";
    case "evidence":
      return category === "evidence" || event.type === "EvidenceReleased" || event.type === "EvidenceWithheld";
    case "claims":
      return category === "claim" || category === "talk" || event.type === "StatementWeighed" || event.type === "CredibilityRevised";
    case "beliefs":
      return category === "belief" || category === "contradiction" || event.type === "DiscrepancyNoticed" || event.type === "CredibilityRevised";
    default:
      if (event.type === "TickStarted" || event.type === "RequestSent" || event.type === "EvidenceObserved") return false;
      if (event.type === "ActionTaken" && event.data.action?.type === "wait") return false;
      if (event.type === "ActionTaken" && ["inspect", "respond", "share", "tell"].includes(event.data.action?.type)) return false; // its result follows
      if (event.type === "CredibilityRevised") return event.data.credibility?.standing !== event.data.before; // a change of standing, not of detail
      if (event.type === "BeliefsRevised") return event.data.prime_before !== event.data.prime_after;
      return true;
  }
}

function involves(event: EventRow, agent: string): boolean {
  if (event.actor === agent) return true;
  const d = event.data;
  return [d.agent, d.sender, d.recipient, d.by, d.on_behalf_of, d.requester, d.against, d.speaker, d.origin].includes(agent) || (Array.isArray(d.audience) && d.audience.includes(agent));
}

export default function Timeline({ events, focusAgent, focusAgentName, onJump }: Props) {
  const [filter, setFilter] = useState<Filter>("key");
  const [onlyAgent, setOnlyAgent] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  const groups = useMemo(() => {
    const result: { tick: number; rows: EventRow[] }[] = [];
    for (const event of events) {
      if (!keep(event, filter)) continue;
      if (onlyAgent && focusAgent && !involves(event, focusAgent)) continue;
      const last = result[result.length - 1];
      if (last && last.tick === event.tick) last.rows.push(event);
      else result.push({ tick: event.tick, rows: [event] });
    }
    return result;
  }, [events, filter, onlyAgent, focusAgent]);

  // Follow the newest events unless the user has scrolled up to read.
  useEffect(() => {
    const el = scroller.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [groups]);

  const shown = groups.reduce((sum, group) => sum + group.rows.length, 0);

  return (
    <div className="panel timeline-panel">
      <header className="panel-head">
        <h2>Timeline</h2>
        <div className="segmented" role="group" aria-label="Timeline filter">
          {FILTERS.map((f) => (
            <button key={f.id} className={filter === f.id ? "on" : ""} title={f.hint} onClick={() => setFilter(f.id)}>
              {f.label}
            </button>
          ))}
        </div>
        {focusAgent && (
          <label className="check">
            <input type="checkbox" checked={onlyAgent} onChange={() => setOnlyAgent(!onlyAgent)} />
            only {focusAgentName}
          </label>
        )}
        <div className="spacer" />
        <span className="muted small">
          {shown} of {events.length} events
        </span>
      </header>
      <div
        className="timeline"
        ref={scroller}
        onScroll={(e) => {
          const el = e.currentTarget;
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
      >
        {groups.length === 0 && <Empty>Nothing to show for this filter yet. Step the simulation to generate events.</Empty>}
        {groups.map((group) => (
          <div key={group.tick} className="tick-group">
            <button className="tick-label" onClick={() => onJump(group.tick)} title="View the investigation as of the end of this tick">
              {group.tick === 0 ? "Setup" : `Tick ${group.tick}`}
            </button>
            <ul>
              {group.rows.map((event) => (
                <li key={event.seq} className={`ev ev-${CATEGORY[event.type] ?? "system"}`} title={`#${event.seq} ${event.type}${event.cause !== null ? ` (caused by #${event.cause})` : ""}`}>
                  <span className="ev-dot" />
                  <span className="ev-text">{event.summary}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}
