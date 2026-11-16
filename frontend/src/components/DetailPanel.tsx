import type { GraphData, GraphEdge, GraphNode, Snapshot } from "../api";
import { Chip, Empty, EvidenceRef, GROUNDS_TEXT, Section, StanceTrail, StatusChip } from "./ui";
import type { NameOf } from "./ui";

interface Props {
  nodeId: string | null;
  graph: GraphData | null;
  snapshot: Snapshot;
  nameOf: NameOf;
  onSelectNode: (nodeId: string | null) => void;
  onSelectAgent: (agent: string) => void;
}

const EDGE_PHRASE: Record<string, [string, string]> = {
  observed: ["found first-hand", "found first-hand by"],
  received: ["was given", "given to"],
  communicated_to: ["passed records to", "received records from"],
  reported: ["said / published", "said or published by"],
  supports: ["supports", "supported by"],
  contradicts: ["contradicts", "contradicts"],
  cites: ["cites", "cited by"],
  associated_with: ["is about", "mentioned in"],
  located_at: ["was kept in", "held"],
  suspects: ["suspects", "suspected by"],
  accused: ["accused", "accused by"],
  distrusts: ["caught withholding", "was caught withholding by"],
  addressed: ["was said to", "was told"],
  relays: ["passes on", "passed on by"],
  witnessed: ["saw for itself", "seen first-hand by"],
  doubts: ["caught out", "was caught out by"],
};

function Relations({ node, graph, onSelectNode }: { node: GraphNode; graph: GraphData; onSelectNode: (id: string) => void }) {
  const labels = Object.fromEntries(graph.nodes.map((n) => [n.id, n.label]));
  const rows = graph.edges
    .filter((edge) => edge.source === node.id || edge.target === node.id)
    .map((edge: GraphEdge) => {
      const outgoing = edge.source === node.id;
      const other = outgoing ? edge.target : edge.source;
      const phrase = (EDGE_PHRASE[edge.type] ?? [edge.type, edge.type])[outgoing ? 0 : 1];
      const sides = (active: boolean) =>
        Object.entries(edge.agents ?? {})
          .filter(([, entry]) => entry.active === active)
          .map(([id]) => labels[`ent:${id}`] ?? id)
          .join(", ");
      const derivation = !edge.rule
        ? null
        : edge.state === "mixed"
          ? `rule ${edge.rule}; holds for ${sides(true)}; defeated for ${sides(false)}`
          : `rule ${edge.rule}${edge.state === "defeated" ? ", defeated" : ""}`;
      const extra = [
        derivation,
        edge.sender ? `from ${labels[`ent:${edge.sender}`] ?? edge.sender}` : null,
        edge.items ? edge.items.join(", ") : null,
        edge.score !== undefined && edge.score !== null ? `score ${edge.score}` : null,
        edge.retracted ? "retracted" : null,
        edge.stance ? edge.stance : null,
      ].filter(Boolean);
      return { edge, other, phrase, extra };
    })
    .sort((a, b) => a.edge.type.localeCompare(b.edge.type) || a.edge.seq - b.edge.seq);
  if (!rows.length) return <Empty>No relationships in this view.</Empty>;
  return (
    <table className="table small">
      <tbody>
        {rows.map(({ edge, other, phrase, extra }) => (
          <tr key={edge.id}>
            <td className="muted nowrap">{phrase}</td>
            <td>
              <button className="link" onClick={() => onSelectNode(other)}>
                {labels[other] ?? other}
              </button>
              {extra.length > 0 && <span className="muted"> ({extra.join("; ")})</span>}
            </td>
            <td
              className="muted nowrap"
              title={
                edge.changed_seq !== undefined && edge.changed_seq !== edge.seq
                  ? `Created by event #${edge.seq}; last changed by event #${edge.changed_seq} (tick ${edge.changed_tick})`
                  : `Created by event #${edge.seq}`
              }
            >
              t{edge.tick} · #{edge.seq}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function DetailPanel({ nodeId, graph, snapshot, nameOf, onSelectNode, onSelectAgent }: Props) {
  const node = graph?.nodes.find((n) => n.id === nodeId) ?? null;
  if (!nodeId || !graph) return <Empty>Select a node in the graph to inspect it: its content, its sources and every relationship with the event that created it.</Empty>;
  if (!node) return <Empty>That item is not part of the graph at this tick or from this perspective.</Empty>;

  const evidence = node.type === "evidence" ? snapshot.evidence[node.ref] : null;
  const claim = node.type === "claim" ? snapshot.claims.find((c) => c.id === node.ref) : null;
  const agent = node.type === "person" && node.agent ? snapshot.agents.find((a) => a.id === node.ref) : null;
  const statement = node.type === "statement" ? snapshot.statements.find((s) => s.id === node.ref) : null;

  return (
    <div className="detail">
      <header className="agent-head">
        <div>
          <div className="muted small">
            {node.type}
            {node.kind ? ` · ${node.kind}` : ""} · first seen tick {node.first_tick} (event #{node.first_seq})
          </div>
          <h2>{node.label}</h2>
        </div>
        <button onClick={() => onSelectNode(null)}>Clear</button>
      </header>

      {evidence && (
        <>
          <p className="quote">{evidence.text}</p>
          <dl className="facts">
            <dt>Kind</dt>
            <dd>
              <Chip tone={`kind-${evidence.kind}`}>{evidence.kind}</Chip>
              {evidence.speaker && <> spoken by {snapshot.entities[evidence.speaker] ? nameOf(evidence.speaker) : "an unnamed source"}</>}
              {!evidence.shareable && <> · protected source, cannot be passed on</>}
            </dd>
            <dt>Source</dt>
            <dd>{evidence.source_name}</dd>
            <dt>First obtained</dt>
            <dd>
              {nameOf(evidence.discovered_by)}, tick {evidence.discovered_tick} ({evidence.discovered_via})
            </dd>
            <dt>Held by</dt>
            <dd>{evidence.holders.map((id) => nameOf(id)).join(", ")}</dd>
            <dt>Asserts</dt>
            <dd>
              {evidence.asserts.map((p) => (
                <div key={p.key}>
                  <button className="link" onClick={() => onSelectNode(`prop:${p.key}`)}>
                    {p.text}
                  </button>
                </div>
              ))}
            </dd>
          </dl>
        </>
      )}

      {claim && (
        <>
          {claim.quote && <p className="quote">{claim.quote}</p>}
          <dl className="facts">
            <dt>Stated by</dt>
            <dd>{claim.by === "anonymous" ? "an anonymous source" : nameOf(claim.by)}</dd>
            <dt>Says</dt>
            <dd>{claim.text}</dd>
            <dt>Status</dt>
            <dd>
              <Chip tone={claim.status === "active" ? "neutral" : "withdrawn"}>{claim.status}</Chip>
              {claim.retracted_tick !== null && ` at tick ${claim.retracted_tick}`}
            </dd>
            <dt>Cites</dt>
            <dd>{claim.cited.length ? claim.cited.map((id) => <EvidenceRef key={id} id={id} onSelect={onSelectNode} />) : "nothing"}</dd>
            <dt>Heard by</dt>
            <dd>{claim.audience.map((id) => nameOf(id)).join(", ")}</dd>
          </dl>
          <p className="muted small">A claim is a statement, not a fact. Listeners weigh it as hearsay, and it never satisfies the standard of proof.</p>
        </>
      )}

      {statement && (
        <>
          <p className="quote">"{statement.text}"</p>
          <dl className="facts" data-testid="statement-detail">
            <dt>Said by</dt>
            <dd>
              {nameOf(statement.speaker)}
              {statement.origin && <> , passing on what {nameOf(statement.origin)} said</>}
            </dd>
            <dt>Said to</dt>
            <dd>{nameOf(statement.recipient)}, tick {statement.tick}</dd>
            <dt>Says</dt>
            <dd>
              <button className="link" onClick={() => onSelectNode(`prop:${statement.proposition}`)}>
                {statement.text}
              </button>
            </dd>
            <dt>{nameOf(statement.recipient)} makes of it</dt>
            {/* The graph node carries the stance only where it is known: the combined view and the
                recipient's own. In the speaker's view it is absent, because nobody told the speaker. */}
            {node.stance !== undefined ? (
              <dd data-testid="statement-stance">
                <StanceTrail stances={statement.stances} />
              </dd>
            ) : (
              <dd className="muted" data-testid="statement-stance-hidden">
                not known from this perspective: {nameOf(statement.recipient)} did not say
              </dd>
            )}
            {/* Absent in the recipient's own view of the graph: the recipient is not told. */}
            {node.grounds !== undefined && (
              <>
                <dt>The speaker</dt>
                <dd>
                  {statement.origin ? `was told so by ${nameOf(statement.origin)}` : GROUNDS_TEXT[statement.grounds]}{" "}
                  {statement.backing.map((id) => (
                    <EvidenceRef key={id} id={id} onSelect={onSelectNode} />
                  ))}
                </dd>
              </>
            )}
          </dl>
          <p className="muted small">A statement is one person's word, weighed as testimony. Repeating it, or having it passed on, does not add to it.</p>
        </>
      )}

      {node.type === "proposition" && (
        <>
          <dl className="facts">
            <dt>Formal</dt>
            <dd>
              <code>{node.ref}</code>
            </dd>
            {node.truth !== undefined && (
              <>
                <dt>Truth</dt>
                <dd>{node.truth === true ? "True" : node.truth === false ? "False" : "Not settled by the scenario"}</dd>
              </>
            )}
          </dl>
          <Section title="What each agent makes of it">
            <table className="table small">
              <tbody>
                {snapshot.agents.map((a) => {
                  const belief = a.beliefs.find((b) => b.key === node.ref);
                  return (
                    <tr key={a.id}>
                      <td>
                        <button className="link" onClick={() => onSelectAgent(a.id)}>
                          {a.name}
                        </button>
                      </td>
                      <td>{belief ? <StatusChip status={belief.status} /> : <span className="muted">unaware</span>}</td>
                      <td className="num">{belief ? `+${belief.support} / -${belief.contra}` : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Section>
        </>
      )}

      {node.type !== "evidence" && node.type !== "claim" && node.type !== "proposition" && node.type !== "statement" && (
        <>
          {node.description && <p>{node.description}</p>}
          <div className="chips">
            {node.agent && <Chip tone="agent">{node.role}</Chip>}
            {node.suspect && <Chip tone="disputed">suspect</Chip>}
          </div>
          {agent && (
            <button className="primary" onClick={() => onSelectAgent(agent.id)}>
              Open {agent.name}'s inspector
            </button>
          )}
          {node.suspect && (
            <Section title="How each agent rates this suspect">
              <table className="table small">
                <thead>
                  <tr>
                    <th>Agent</th>
                    <th>Opp.</th>
                    <th>Means</th>
                    <th>Motive</th>
                    <th className="num">Score</th>
                  </tr>
                </thead>
                <tbody>
                  {snapshot.agents.map((a) => {
                    const s = a.suspects[node.ref];
                    return (
                      <tr key={a.id} className={a.prime_suspect === node.ref ? "prime" : ""}>
                        <td>{a.name}</td>
                        <td>{s ? <Chip tone={`opp-${s.opportunity}`}>{s.opportunity}</Chip> : "-"}</td>
                        <td>{s?.means ? "yes" : "-"}</td>
                        <td>{s && s.motive !== "none" ? s.motive : "-"}</td>
                        <td className="num">{s?.score ?? 0}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Section>
          )}
        </>
      )}

      <Section title="Relationships and provenance">
        <Relations node={node} graph={graph} onSelectNode={onSelectNode} />
      </Section>
    </div>
  );
}
