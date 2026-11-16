import type { ReactNode } from "react";
import type { Ratio } from "../api";

export type NameOf = (id: string | null | undefined) => string;

export function Chip({ tone = "neutral", title, children }: { tone?: string; title?: string; children: ReactNode }) {
  return (
    <span className={`chip chip-${tone}`} title={title}>
      {children}
    </span>
  );
}

export function StatusChip({ status }: { status: string }) {
  return <Chip tone={status}>{status}</Chip>;
}

/** A count with its denominator. Shows "n/a" rather than a percentage when there is nothing to divide by. */
export function RatioBar({ label, ratio, hint, invert = false }: { label: string; ratio: Ratio; hint?: string; invert?: boolean }) {
  const pct = ratio.pct;
  const good = pct === null ? "none" : (invert ? 100 - pct : pct) >= 67 ? "good" : (invert ? 100 - pct : pct) >= 34 ? "mid" : "bad";
  return (
    <div className="ratio" title={hint}>
      <div className="ratio-head">
        <span>{label}</span>
        <span className="ratio-value">
          {ratio.num}/{ratio.den}
          <span className="muted"> {pct === null ? "n/a" : `${pct}%`}</span>
        </span>
      </div>
      <div className="ratio-track">
        <div className={`ratio-fill ratio-${good}`} style={{ width: `${pct ?? 0}%` }} />
      </div>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Section({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="section">
      <header className="section-head">
        <h3>{title}</h3>
        {aside}
      </header>
      {children}
    </section>
  );
}

/** A clickable evidence id that selects the record in the graph. */
export function EvidenceRef({ id, onSelect, title }: { id: string; onSelect: (nodeId: string) => void; title?: string }) {
  // Ids the engine hands out: C<n> a public claim, S<n> a spoken statement, O<n> something the agent saw itself.
  if (/^O\d+$/.test(id)) {
    return (
      <span className="ref static" title={title ?? "Something this agent saw for itself"}>
        {id}
      </span>
    );
  }
  const isStatement = /^S\d+$/.test(id);
  const isClaim = !isStatement && id.startsWith("C");
  return (
    <button
      className="ref"
      title={title ?? (isStatement ? "Spoken statement" : isClaim ? "Public claim" : "Evidence record")}
      onClick={() => onSelect(isStatement ? `st:${id}` : isClaim ? `claim:${id}` : `ev:${id}`)}
    >
      {id}
    </button>
  );
}

const STANCE_TONE: Record<string, string> = { accepted: "believed", questioned: "disputed", rejected: "rejected" };

/** What a listener makes of a statement, with every earlier stance kept in view. */
export function StanceTrail({ stances }: { stances: { stance: string; tick: number }[] }) {
  if (!stances.length) return <span className="muted">not yet weighed</span>;
  return (
    <span className="stance-trail" data-testid="stance-trail">
      {stances.map((s, index) => (
        <span key={`${s.tick}-${s.stance}`}>
          {index > 0 && <span className="muted"> → </span>}
          <Chip tone={STANCE_TONE[s.stance] ?? "neutral"} title={`Since tick ${s.tick}`}>
            {s.stance} t{s.tick}
          </Chip>
        </span>
      ))}
    </span>
  );
}

export const GROUNDS_TEXT: Record<string, string> = {
  observed: "saw it for themselves",
  held: "holds a record that says so",
  heard: "was told so",
  none: "had nothing for it",
};

export const shortHash = (hash: string) => hash.slice(0, 10);
