import cytoscape from "cytoscape";
import type { Core, ElementDefinition } from "cytoscape";
import { useEffect, useMemo, useRef, useState } from "react";
import type { BeliefStatus, GraphData, GraphEdge, GraphNode } from "../api";

interface Props {
  graph: GraphData | null;
  selected: string | null;
  onSelect: (nodeId: string | null) => void;
  perspective: string;
  onPerspective: (value: string) => void;
  agents: { id: string; name: string }[];
}

type Column = "agent" | "evidence" | "proposition" | "entity";
const COLUMN_X: Record<Column, number> = { agent: 0, evidence: 340, proposition: 740, entity: 1120 };
const SPACING: Record<Column, number> = { agent: 130, evidence: 44, proposition: 40, entity: 56 };
const COLUMN_TITLE: Record<Column, string> = { agent: "Agents", evidence: "Evidence, claims and statements", proposition: "What it asserts", entity: "About" };

function columnOf(node: GraphNode): Column {
  if (node.type === "evidence" || node.type === "claim" || node.type === "statement") return "evidence";
  if (node.type === "proposition") return "proposition";
  return node.type === "person" && node.agent ? "agent" : "entity";
}

/** In the all-agents view a proposition gets one colour summarising what the agents make of it. */
function consensus(statuses: Record<string, BeliefStatus> | undefined): string | undefined {
  const values = Object.values(statuses ?? {});
  if (!values.length) return undefined;
  const believed = values.some((v) => v === "believed");
  const rejected = values.some((v) => v === "rejected");
  if (believed && rejected) return "disputed";
  if (believed) return "believed";
  if (rejected) return "rejected";
  if (values.some((v) => v === "disputed")) return "disputed";
  if (values.every((v) => v === "withdrawn")) return "withdrawn";
  return "tentative";
}

/**
 * Layered "evidence board": who knows -> what record -> what it asserts -> who or what it is about.
 * Positions are a pure function of the graph, so stepping the simulation never reshuffles the picture.
 * Propositions and entities are ordered by the average row of their neighbours to keep edges short.
 */
function boardPositions(nodes: GraphNode[], edges: GraphEdge[]): Record<string, { x: number; y: number }> {
  const byColumn: Record<Column, GraphNode[]> = { agent: [], evidence: [], proposition: [], entity: [] };
  for (const node of nodes) byColumn[columnOf(node)].push(node);

  byColumn.agent.sort((a, b) => a.ref.localeCompare(b.ref));
  byColumn.evidence.sort((a, b) => a.first_seq - b.first_seq || a.id.localeCompare(b.id));
  const row: Record<string, number> = {};
  byColumn.evidence.forEach((node, index) => (row[node.id] = index));

  const barycentre = (pick: (edge: GraphEdge) => string | null): number => {
    const rows = edges.map(pick).filter((other): other is string => other !== null && other in row).map((other) => row[other]);
    return rows.length ? rows.reduce((sum, value) => sum + value, 0) / rows.length : Number.POSITIVE_INFINITY;
  };

  const propKey: Record<string, number> = {};
  for (const node of byColumn.proposition) {
    propKey[node.id] = barycentre((e) => (e.type === "supports" && e.target === node.id && !e.source.startsWith("prop:") ? e.source : null));
  }
  for (const node of byColumn.proposition) {
    if (propKey[node.id] !== Number.POSITIVE_INFINITY) continue;
    // Known only by derivation: sit next to the premises.
    const premises = edges.filter((e) => e.type === "supports" && e.target === node.id && e.source in propKey).map((e) => propKey[e.source]).filter(Number.isFinite);
    if (premises.length) propKey[node.id] = premises.reduce((s, v) => s + v, 0) / premises.length + 0.01;
  }
  byColumn.proposition.sort((a, b) => propKey[a.id] - propKey[b.id] || a.id.localeCompare(b.id));
  byColumn.proposition.forEach((node, index) => (row[node.id] = (index * SPACING.proposition) / SPACING.evidence));

  const entityKey: Record<string, number> = {};
  for (const node of byColumn.entity) {
    entityKey[node.id] = barycentre((e) => (e.type === "associated_with" && e.target === node.id ? e.source : null));
  }
  byColumn.entity.sort((a, b) => entityKey[a.id] - entityKey[b.id] || a.label.localeCompare(b.label));

  const positions: Record<string, { x: number; y: number }> = {};
  (Object.keys(byColumn) as Column[]).forEach((column) => {
    const list = byColumn[column];
    list.forEach((node, index) => {
      positions[node.id] = { x: COLUMN_X[column], y: (index - (list.length - 1) / 2) * SPACING[column] };
    });
  });
  return positions;
}

const STYLE: cytoscape.StylesheetJson = [
  {
    selector: "node",
    style: {
      label: "data(label)",
      color: "#d5dbe5",
      "font-size": 10,
      "font-family": "Inter, Segoe UI, system-ui, sans-serif",
      "text-valign": "center",
      "text-halign": "center",
      "text-wrap": "ellipsis",
      "text-max-width": "190px",
      "background-color": "#232b38",
      "border-width": 1,
      "border-color": "#465368",
    },
  },
  { selector: 'node[type = "person"]', style: { shape: "ellipse", width: 30, height: 30, "background-color": "#56637a", "text-halign": "right", "text-margin-x": 6, "text-max-width": "160px" } },
  { selector: "node[?suspect]", style: { "border-color": "#e0a84b", "border-width": 2 } },
  { selector: "node[?agent]", style: { width: 52, height: 52, "background-color": "#2f6fae", "border-color": "#9fcbf5", "border-width": 2, "font-size": 11, "font-weight": 600, "text-halign": "center", "text-valign": "bottom", "text-margin-x": 0, "text-margin-y": 5 } },
  { selector: 'node[type = "location"]', style: { shape: "round-diamond", width: 28, height: 28, "background-color": "#3f7d5a", "border-color": "#7fc79c", "text-halign": "right", "text-margin-x": 6, "text-max-width": "160px" } },
  { selector: 'node[type = "object"]', style: { shape: "hexagon", width: 30, height: 28, "background-color": "#9a7a22", "border-color": "#e3c35d", "text-halign": "right", "text-margin-x": 6, "text-max-width": "160px" } },
  { selector: 'node[type = "evidence"]', style: { shape: "round-rectangle", width: 216, height: 32, "background-color": "#1c2430", "border-width": 2 } },
  { selector: 'node[kind = "forensic"]', style: { "border-color": "#c39bd3" } },
  { selector: 'node[kind = "record"]', style: { "border-color": "#7aa9d6" } },
  { selector: 'node[kind = "testimony"]', style: { "border-color": "#d9b65a" } },
  { selector: 'node[kind = "hearsay"]', style: { "border-color": "#d98c6a", "border-style": "dashed" } },
  { selector: 'node[type = "claim"]', style: { shape: "round-tag", width: 216, height: 32, "background-color": "#3a2924", "border-color": "#d98c6a", "border-width": 2 } },
  { selector: 'node[type = "statement"]', style: { shape: "round-tag", width: 216, height: 32, "background-color": "#2b2a1c", "border-color": "#d9b65a", "border-width": 2 } },
  { selector: 'node[type = "statement"][stance = "rejected"]', style: { "border-color": "#e06c66", "border-style": "dashed" } },
  { selector: 'node[type = "statement"][stance = "questioned"]', style: { "border-color": "#e0a84b", "border-style": "dashed" } },
  { selector: "node[?retracted]", style: { opacity: 0.5, "border-style": "dashed" } },
  { selector: 'node[type = "proposition"]', style: { shape: "round-rectangle", width: 262, height: 30, "text-max-width": "248px", "background-color": "#252d3a", "border-color": "#56637a" } },
  { selector: 'node[status = "believed"]', style: { "background-color": "#1d4a36", "border-color": "#52b788" } },
  { selector: 'node[status = "tentative"]', style: { "border-color": "#93a1b3" } },
  { selector: 'node[status = "disputed"]', style: { "background-color": "#4b3a14", "border-color": "#e0a84b" } },
  { selector: 'node[status = "rejected"]', style: { "background-color": "#4a2020", "border-color": "#e06c66" } },
  { selector: 'node[status = "withdrawn"]', style: { opacity: 0.55, "border-style": "dashed" } },
  { selector: 'node[type = "header"]', style: { "background-opacity": 0, "border-width": 0, width: 10, height: 10, "font-size": 13, "font-weight": 600, color: "#8492a6", "text-transform": "uppercase", "text-wrap": "none", events: "no" } },
  { selector: "node[?fresh]", style: { "underlay-color": "#ffd166", "underlay-opacity": 0.28, "underlay-padding": 7, "underlay-shape": "round-rectangle" } },
  { selector: "node:selected", style: { "border-color": "#ffffff", "border-width": 3 } },
  {
    selector: "edge",
    style: {
      width: 1.2,
      "line-color": "#3a4556",
      "target-arrow-color": "#3a4556",
      "target-arrow-shape": "triangle",
      "arrow-scale": 0.8,
      "curve-style": "bezier",
      opacity: 0.75,
    },
  },
  { selector: "edge[?samecol]", style: { "curve-style": "unbundled-bezier", "control-point-distances": [-90], "control-point-weights": [0.5] } },
  { selector: 'edge[type = "supports"]', style: { "line-color": "#62758d", "target-arrow-color": "#62758d" } },
  { selector: 'edge[type = "observed"]', style: { "line-color": "#3d86bd", "target-arrow-color": "#3d86bd" } },
  { selector: 'edge[type = "received"]', style: { "line-color": "#3d86bd", "target-arrow-color": "#3d86bd", "line-style": "dashed" } },
  { selector: 'edge[type = "communicated_to"]', style: { "line-color": "#9fcbf5", "target-arrow-color": "#9fcbf5", width: 2 } },
  { selector: 'edge[type = "reported"]', style: { "line-color": "#d9b65a", "target-arrow-color": "#d9b65a", "line-style": "dotted", width: 1.6 } },
  { selector: 'edge[type = "cites"]', style: { "line-color": "#d98c6a", "target-arrow-color": "#d98c6a", "line-style": "dotted", width: 1.6 } },
  { selector: 'edge[type = "associated_with"]', style: { "line-color": "#2c3644", "target-arrow-shape": "none", width: 1 } },
  { selector: 'edge[type = "located_at"]', style: { "line-color": "#9a7a22", "target-arrow-color": "#9a7a22" } },
  { selector: 'edge[type = "contradicts"]', style: { "line-color": "#e06c66", "target-arrow-shape": "none", "line-style": "dashed", width: 2.2, opacity: 0.95 } },
  { selector: 'edge[type = "suspects"]', style: { "line-color": "#e0a84b", "target-arrow-color": "#e0a84b", "line-style": "dashed", width: 2 } },
  { selector: 'edge[type = "accused"]', style: { "line-color": "#ff5d5d", "target-arrow-color": "#ff5d5d", width: 3.5, opacity: 1 } },
  { selector: 'edge[type = "distrusts"]', style: { "line-color": "#ff5d5d", "target-arrow-color": "#ff5d5d", "line-style": "dotted", width: 2.4, opacity: 1 } },
  { selector: 'edge[type = "addressed"]', style: { "line-color": "#d9b65a", "target-arrow-color": "#d9b65a", "line-style": "dashed", width: 1.4 } },
  { selector: 'edge[type = "relays"]', style: { "line-color": "#d98c6a", "target-arrow-color": "#d98c6a", "line-style": "dotted", width: 1.6 } },
  { selector: 'edge[type = "witnessed"]', style: { "line-color": "#52b788", "target-arrow-color": "#52b788", width: 1.6 } },
  { selector: 'edge[type = "doubts"]', style: { "line-color": "#ff5d5d", "target-arrow-color": "#ff5d5d", "line-style": "dashed", width: 2.4, opacity: 1 } },
  { selector: "edge[?inactive]", style: { opacity: 0.3, "line-style": "dashed" } },
  { selector: "edge[?mixed]", style: { opacity: 0.7, "line-style": "dashed" } },
  { selector: ".faded", style: { opacity: 0.1 } },
  {
    selector: "edge.lit",
    style: {
      width: 2.4,
      opacity: 1,
      label: "data(label)",
      "font-size": 9,
      color: "#e8edf4",
      "text-background-color": "#10151c",
      "text-background-opacity": 0.9,
      "text-background-padding": "2px",
      "text-rotation": "autorotate",
    },
  },
];

const LEGEND: { cls: string; label: string }[] = [
  { cls: "lg-agent", label: "Agent" },
  { cls: "lg-person", label: "Person" },
  { cls: "lg-record", label: "Record" },
  { cls: "lg-testimony", label: "Testimony" },
  { cls: "lg-hearsay", label: "Hearsay / claim" },
  { cls: "lg-believed", label: "Believed" },
  { cls: "lg-disputed", label: "Disputed" },
  { cls: "lg-rejected", label: "Rejected" },
];

export default function GraphPanel({ graph, selected, onSelect, perspective, onPerspective, agents }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const fitted = useRef<string>("");
  const [layout, setLayout] = useState<"board" | "force">("board");
  const [show, setShow] = useState({ propositions: true, entities: true, about: true, holdings: true });

  useEffect(() => {
    if (!container.current) return;
    const cy = cytoscape({ container: container.current, style: STYLE, minZoom: 0.15, maxZoom: 2.5, wheelSensitivity: 0.25, boxSelectionEnabled: false });
    cy.on("tap", "node", (event) => {
      if (!event.target.id().startsWith("hdr:")) onSelectRef.current(event.target.id());
    });
    cy.on("tap", (event) => {
      if (event.target === cy) onSelectRef.current(null);
    });
    cyRef.current = cy;
    const observer = new ResizeObserver(() => cy.resize());
    observer.observe(container.current);
    return () => {
      observer.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  const visible = useMemo(() => {
    if (!graph) return { nodes: [] as GraphNode[], edges: [] as GraphEdge[] };
    const nodes = graph.nodes.filter((node) => {
      if (node.type === "proposition") return show.propositions;
      if (node.type === "location" || node.type === "object" || (node.type === "person" && !node.agent)) return show.entities;
      return true;
    });
    const ids = new Set(nodes.map((n) => n.id));
    const edges = graph.edges.filter((edge) => {
      if (!ids.has(edge.source) || !ids.has(edge.target)) return false;
      if (edge.type === "associated_with") return show.about;
      if (edge.type === "observed" || edge.type === "received") return show.holdings;
      return true;
    });
    return { nodes, edges };
  }, [graph, show]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy || !graph) return;
    const columns: Record<string, Column> = {};
    for (const node of visible.nodes) columns[node.id] = columnOf(node);
    const positions = boardPositions(visible.nodes, visible.edges);
    const elements: ElementDefinition[] = [];
    for (const node of visible.nodes) {
      const status = node.type === "proposition" ? (graph.perspective === "all" ? consensus(node.statuses) : node.status ?? undefined) : undefined;
      const mark = node.truth === true ? "✓ " : node.truth === false ? "✗ " : "";
      const prefix = node.type === "evidence" ? `${node.ref}  ` : "";
      elements.push({
        group: "nodes",
        data: {
          id: node.id,
          label: mark + prefix + node.label,
          type: node.type,
          kind: node.kind,
          status,
          agent: node.agent || undefined,
          suspect: node.suspect || undefined,
          retracted: node.type === "claim" && node.status === "retracted" ? true : undefined,
          fresh: graph.tick > 0 && node.first_tick === graph.tick ? true : undefined,
        },
        position: { ...positions[node.id] },
      });
    }
    if (layout === "board") {
      // Column headings live in the graph itself so they pan and zoom with it.
      (Object.keys(COLUMN_TITLE) as Column[]).forEach((column) => {
        const ys = visible.nodes.filter((n) => columns[n.id] === column).map((n) => positions[n.id].y);
        if (!ys.length) return;
        elements.push({
          group: "nodes",
          data: { id: `hdr:${column}`, label: COLUMN_TITLE[column], type: "header" },
          position: { x: COLUMN_X[column], y: Math.min(...ys) - 52 },
          selectable: false,
          grabbable: false,
        });
      });
    }
    for (const edge of visible.edges) {
      elements.push({
        group: "edges",
        data: {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          type: edge.type,
          label: edge.rule ? (edge.state === "mixed" ? `${edge.rule} (agents differ)` : edge.rule) : edge.label ?? edge.type,
          samecol: columns[edge.source] === columns[edge.target] ? true : undefined,
          inactive: edge.active === false || edge.retracted ? true : undefined,
          mixed: edge.state === "mixed" ? true : undefined,
        },
      });
    }
    const viewport = { zoom: cy.zoom(), pan: cy.pan() };
    cy.batch(() => {
      cy.elements().remove();
      cy.add(elements);
    });
    if (layout === "force") {
      cy.layout({ name: "cose", animate: false, randomize: false, nodeRepulsion: () => 90000, idealEdgeLength: () => 110, nodeOverlap: 24, padding: 30 } as cytoscape.LayoutOptions).run();
    }
    // Keep the user's zoom and pan while stepping; refit only when the kind of picture changes.
    const frame = `${graph.perspective}|${layout}|${visible.nodes.length > 0}`;
    if (fitted.current !== frame) {
      cy.fit(undefined, 40);
      fitted.current = frame;
    } else {
      cy.viewport(viewport);
    }
  }, [graph, visible, layout]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass("faded lit");
    cy.nodes().unselect();
    if (!selected) return;
    const node = cy.$id(selected);
    if (node.empty()) return;
    node.select();
    const neighbourhood = node.closedNeighborhood();
    cy.elements().not(neighbourhood).addClass("faded");
    neighbourhood.edges().addClass("lit");
  }, [selected, graph, visible, layout]);

  const toggle = (key: keyof typeof show) => setShow((current) => ({ ...current, [key]: !current[key] }));

  return (
    <div className="panel graph-panel">
      <header className="panel-head">
        <h2>Knowledge graph</h2>
        <label className="inline">
          Seen by
          <select value={perspective} onChange={(e) => onPerspective(e.target.value)} aria-label="Graph perspective">
            <option value="all">All agents</option>
            {agents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </select>
        </label>
        <div className="toggles">
          {(["propositions", "entities", "about", "holdings"] as const).map((key) => (
            <label key={key} className="check">
              <input type="checkbox" checked={show[key]} onChange={() => toggle(key)} />
              {key === "about" ? "about-links" : key === "holdings" ? "who-holds links" : key}
            </label>
          ))}
        </div>
        <div className="spacer" />
        <div className="segmented" role="group" aria-label="Graph layout">
          <button className={layout === "board" ? "on" : ""} onClick={() => setLayout("board")}>
            Board
          </button>
          <button className={layout === "force" ? "on" : ""} onClick={() => setLayout("force")}>
            Force
          </button>
        </div>
        <button onClick={() => cyRef.current?.fit(undefined, 40)}>Fit</button>
      </header>
      <div className="graph-wrap">
        <div ref={container} className="graph-canvas" />
        <div className="legend">
          {LEGEND.map((item) => (
            <span key={item.label}>
              <i className={`lg ${item.cls}`} />
              {item.label}
            </span>
          ))}
          <span>
            <i className="lg lg-fresh" />
            New this tick
          </span>
          {graph?.truth_shown && <span>{"✓ / ✗ truth revealed"}</span>}
        </div>
      </div>
    </div>
  );
}
