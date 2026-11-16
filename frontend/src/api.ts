// Typed client for the CaseForge API. Every function here performs a real request.

export interface RunSummary {
  id: string;
  label: string;
  scenario_id: string;
  scenario_version: string;
  seed: number;
  tick: number;
  max_ticks: number;
  status: "running" | "closed";
  close_reason: string | null;
  seq: number;
  head_hash: string;
  parent_run_id: string | null;
  fork_tick: number | null;
  revealed: boolean;
  created_at: string;
  policies: Record<string, string>;
  interventions: string[];
  accused: string | null;
  // False for a run recorded by another engine or scenario version: it can be listed and deleted, not opened.
  compatible: boolean;
  incompatible_reason: string | null;
  // False for a run this build can read but must not add to: its log would not be reproduced by the current rules.
  continuable: boolean;
  compatibility: Compatibility | null;
}

export interface Compatibility {
  state: "current" | "verified" | "behaviour_changed";
  continuable: boolean;
  legacy: boolean; // stored before runs carried a stamp
  stamped_rules: string | null;
  current_rules: string;
  stamped_fingerprint: string | null;
  current_fingerprint: string;
  first_divergence: number | null;
  detail: string;
}

export interface ScenarioSummary {
  id: string;
  version: string;
  title: string;
  briefing: string;
  max_ticks: number;
  evidence_total: number;
  agents: { id: string; name: string; role: string; goals: string[] }[];
  suspects: { id: string; name: string }[];
  interventions: { id: string; label: string; description: string; kind: string }[];
  policies: Record<string, string>;
}

export type BeliefStatus = "believed" | "tentative" | "disputed" | "rejected" | "withdrawn";

export interface Derivation {
  rule: string;
  premises: string[];
  active: boolean;
  defeated_by: string | null;
}

export interface Belief {
  key: string;
  text: string;
  predicate: string;
  status: BeliefStatus;
  support: number;
  contra: number;
  evidence: string[];
  against: string[];
  derivations: Derivation[];
}

export interface Assessment {
  score: number;
  opportunity: "strong" | "weak" | "none" | "contested" | "alibi";
  means: boolean;
  motive: "strong" | "weak" | "none";
  named: number;
  evidence: string[];
}

export interface Holding {
  id: string;
  tick: number;
  seq: number;
  via: string;
  from_agent: string | null;
  chain: string[];
}

export interface AgentSnap {
  id: string;
  name: string;
  role: string;
  goals: string[];
  policy: string;
  disposition: Record<string, unknown>;
  prime_suspect: string | null;
  suspects: Record<string, Assessment>;
  beliefs: Belief[];
  holdings: Holding[];
  contradictions: { pair: string; a: string; b: string }[];
  sources: { id: string; name: string; mode: string }[];
  actions: number;
  rejected: number;
  // Answers to this agent's requests that it caught leaving a record out.
  discrepancies: { against: string; request: string; evidence: string; tick: number; seq: number }[];
  escalated: string[];
  // What this agent saw for itself. Private to it; the observer sees it like any holding.
  observations: { id: string; key: string; text: string }[];
  // What this agent could check of other people's word. Its own judgment, from its own records.
  credibility: CredibilitySnap[];
}

export interface CredibilitySnap {
  speaker: string;
  name: string;
  standing: "impeached" | "corroborated";
  refuted: { key: string; text: string }[];
  corroborated: { key: string; text: string }[];
  history: { standing: string | null; seq: number; tick: number }[];
}

export type Stance = "accepted" | "questioned" | "rejected";

export interface StatementSnap {
  id: string;
  speaker: string;
  recipient: string;
  proposition: string;
  text: string;
  origin: string | null; // whose word it is, when the speaker only passes it on
  relays: string | null;
  tick: number;
  seq: number;
  // What the speaker had for it. The speaker knows; the recipient's own view never does.
  grounds: "observed" | "held" | "heard" | "none";
  backing: string[];
  stance: Stance | null;
  stances: { stance: Stance; belief: string; seq: number; tick: number }[];
}

export interface Agenda {
  protects: string;
  deflects_to: string | null;
  leaks_to: string | null;
  note: string;
  policy: string; // the policy the agent is running; only "deceptive" acts on an agenda
}

export interface EvidenceSnap {
  id: string;
  title: string;
  text: string;
  kind: "forensic" | "record" | "testimony" | "hearsay";
  speaker: string | null;
  source: string;
  source_name: string;
  mentions: string[];
  asserts: { key: string; text: string }[];
  shareable: boolean;
  discovered_by: string;
  discovered_tick: number;
  discovered_via: string;
  holders: string[];
}

export interface ClaimSnap {
  id: string;
  by: string;
  proposition: string;
  text: string;
  quote: string | null;
  cited: string[];
  audience: string[];
  tick: number;
  status: "active" | "retracted";
  retracted_tick: number | null;
}

export interface RequestSnap {
  id: string;
  sender: string;
  recipient: string;
  topic: string;
  source: string | null;
  source_name: string | null;
  tick: number;
  status: string;
  answered_tick: number | null;
  evidence: string[];
  // Found by the search but not handed over. The responder knows; the requester's own view never does.
  withheld: string[];
}

export interface Progress {
  tick: number;
  max_ticks: number;
  status: string;
  evidence_discovered: number;
  evidence_total: number;
  claims_published: number;
  contradictions_recognized: number;
  requests: number;
  actions: number;
}

export interface Snapshot {
  tick: number;
  seq: number;
  status: "running" | "closed";
  close_reason: string | null;
  accusation: { by: string; suspect: string; cited: string[]; seq: number; tick: number } | null;
  case: { title: string; briefing: string; object: string; crime_location: string; suspects: string[]; max_ticks: number };
  entities: Record<string, { id: string; kind: string; name: string; description: string }>;
  sources: Record<string, { id: string; name: string; kind: string; description: string; operators: string[]; requesters: string[]; self_serve: boolean }>;
  agents: AgentSnap[];
  evidence: Record<string, EvidenceSnap>;
  evidence_total: number;
  claims: ClaimSnap[];
  requests: RequestSnap[];
  statements: StatementSnap[];
  interventions: { id: string; label: string; description: string; kind: string; applied: boolean }[];
  propositions: Record<string, string>;
  run: RunSummary;
  latest_tick: number;
  is_latest: boolean;
  progress: Progress;
  // Scenario-private. Present only once the case is closed or the solution was revealed.
  agendas?: Record<string, Agenda>;
}

export interface EventRow {
  seq: number;
  tick: number;
  type: string;
  actor: string;
  cause: number | null;
  // Payload shape depends on the event type; see docs/EVENT_MODEL.md.
  data: Record<string, any>;
  hash: string;
  summary: string;
}

export interface GraphNode {
  id: string;
  type: "person" | "location" | "object" | "evidence" | "proposition" | "claim" | "statement";
  label: string;
  ref: string;
  first_seq: number;
  first_tick: number;
  description?: string;
  agent?: boolean;
  role?: string | null;
  suspect?: boolean;
  kind?: string;
  speaker?: string | null;
  holders?: string[];
  predicate?: string;
  statuses?: Record<string, BeliefStatus>;
  status?: string | null; // belief status on propositions (single-agent view); active/retracted on claims
  truth?: boolean | null;
  by?: string;
  text?: string | null;
  // Statements: recipient, whose word it is, what the speaker had for it, what the recipient makes of it.
  to?: string;
  origin?: string | null;
  grounds?: string;
  stance?: Stance;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  seq: number;
  tick: number;
  label?: string;
  kind?: string;
  sender?: string | null;
  chain?: string[];
  items?: string[];
  rule?: string;
  // Derivations: null when the agents holding it disagree; `state` spells that out.
  active?: boolean | null;
  state?: "active" | "defeated" | "mixed";
  // Reasoning edges: the same facts per agent, and the event that last changed the edge.
  agents?: Record<string, { seq: number; tick: number; active?: boolean; defeated_by?: string | null; changed_seq?: number; changed_tick?: number }>;
  changed_seq?: number;
  changed_tick?: number;
  score?: number | null;
  via?: string;
  retracted?: boolean;
  stance?: Stance;
}

export interface GraphData {
  perspective: string;
  tick: number;
  seq: number;
  nodes: GraphNode[];
  edges: GraphEdge[];
  truth_shown: boolean;
}

export interface Ratio {
  num: number;
  den: number;
  pct: number | null;
}

export interface StatementResult {
  id: string;
  speaker: string;
  recipient: string;
  voice: string;
  passed_on: boolean;
  proposition: string;
  tick: number;
  grounds: string;
  backing: string[];
  true: boolean | null;
  stances: { stance: Stance; tick: number }[];
  first_stance: Stance | null;
  final_stance: Stance | null;
  ever_accepted: boolean;
  voice_standing_with_recipient: string | null;
}

export interface EvaluationResult {
  outcome: "solved" | "wrong_accusation" | "unresolved";
  // Right or wrong, and justified or not, as separate questions.
  category: "correct_supported" | "correct_unsupported" | "wrong_supported" | "wrong_unsupported" | "unresolved";
  culprit: string;
  accused: string | null;
  accusation_tick: number | null;
  accusation_supported: boolean | null;
  close_reason: string | null;
  lead: string;
  solution: string;
  evidence: {
    key_discovered: Ratio;
    key_held_by_lead: Ratio;
    all_discovered: Ratio;
    undiscovered: { id: string; title: string; key: boolean }[];
    discoveries: { id: string; title: string; by: string; tick: number; via: string; key: boolean }[];
  };
  key_facts: { established_by_lead: Ratio; items: { proposition: string; status: string; established: boolean }[] };
  claims: {
    published_by_agents: number;
    rumors_injected: number;
    unsupported: Ratio;
    unsupported_guilt: Ratio;
    false: Ratio;
    false_retracted: Ratio;
    true_retracted: number;
    items: { id: string; by: string; proposition: string; tick: number; guilt: boolean; true: boolean | null; supported: boolean; retracted: boolean; retracted_tick: number | null }[];
  };
  contradictions: {
    inherent_recognized_by_team: Ratio;
    resolved_correctly: Ratio;
    resolved_correctly_by_lead: Ratio;
    inherent: { pair: string; recognized_by: string[] }[];
  };
  agents: Record<string, {
    belief_accuracy: Ratio;
    false_beliefs: string[];
    wrongly_rejected: string[];
    prime_suspect: string | null;
    prime_correct: boolean | null;
    evidence_held: number;
    actions: number;
    rejected_actions: number;
    contradictions_resolved: Ratio;
  }>;
  effort: {
    ticks: number;
    events: number;
    actions: number;
    rejected_actions: number;
    waits: number;
    inspections: number;
    empty_inspections: number;
    redundant_inspections: number;
    requests: number;
    interventions: string[];
  };
  deception: {
    answers_with_withholding: number;
    records_withheld: string[];
    key_records_withheld: Ratio;
    noticed: Ratio;
    recovered: Ratio;
    escalations: { by: string; against: string; tick: number; grounds: string[]; sources: string[] }[];
    items: { request: string; by: string; from: string; source: string | null; topic: string; tick: number | null; evidence: string[]; key: string[]; noticed_tick: number | null; recovered: string[] }[];
    agendas: Record<string, Agenda>;
  };
  testimony: {
    statements: number;
    first_hand: number;
    passed_on: number;
    without_grounds: Ratio;
    false: Ratio;
    false_ever_accepted: Ratio;
    false_accepted_at_close: Ratio;
    false_rejected_at_close: Ratio;
    true_rejected_at_close: Ratio;
    false_speakers_impeached: Ratio;
    truthful_speakers_impeached: Ratio;
    refuted_claims_false: Ratio;
    corroborated_claims_true: Ratio;
    items: StatementResult[];
  };
  provenance: { id: string; title: string; kind: string; key: boolean; first_found_by: string | null; first_found_tick: number | null; reached_accuser_tick: number | null; chain: string[] }[];
}

export interface Evaluation {
  available: boolean;
  reason?: string;
  progress: Progress;
  result?: EvaluationResult;
}

export interface Check {
  ok: boolean | null;
  detail: string;
  first_divergence?: number | null;
}

export interface VerifyReport {
  chain: Check;
  fold: Check;
  decisions: Check;
  policies: Check;
  head_hash: string;
  compatibility: Compatibility;
  stored_matches_memory: boolean;
  // The log this report is about. A report is current only while the run's head still equals head_hash.
  run_id: string;
  events: number;
  tick: number;
}

export interface CompareSide {
  run: RunSummary;
  progress: Progress;
  metrics: Record<string, string | number | boolean | null> | null;
}

export interface Comparison {
  a: CompareSide;
  b: CompareSide;
  common_events: number;
  identical: boolean;
  divergence: { seq: number; tick: number; a: EventRow[]; b: EventRow[] } | null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  } catch {
    throw new ApiError(0, "Cannot reach the CaseForge server. Is `python -m caseforge serve` running?");
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let body: any = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  if (!response.ok) {
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d: any) => d.msg).join("; ") : `Request failed (${response.status})`;
    throw new ApiError(response.status, message);
  }
  return body as T;
}

const post = <T>(path: string, body?: unknown) => call<T>(path, { method: "POST", body: JSON.stringify(body ?? {}) });

function query(params: Record<string, string | number | null | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, value]) => value !== null && value !== undefined)
    .map(([key, value]) => `${key}=${encodeURIComponent(String(value))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

// -- the counterfactual laboratory --------------------------------------------------------------

export type OutcomeCategory = "correct_supported" | "correct_unsupported" | "wrong_supported" | "wrong_unsupported" | "unresolved";
export type LabPair = [number, number];

export interface LabExpectation {
  id: string;
  kind: "contract" | "design" | "ideal";
  says?: string; // withheld until the ground truth is revealed
  held: number;
  of: number;
  predicted: string;
  observed: string;
  prediction_right: boolean | null;
  failed_seeds: number[];
}

export interface LabAggregate {
  runs: number;
  categories: Record<OutcomeCategory, number>;
  verdicts: Record<string, number>;
  accused?: Record<string, number>; // revealed only
  false_accusations: number;
  median_ticks_when_solved: number | null;
  ticks_range_when_solved: [number, number] | null;
  median_ticks: number | null;
  median_actions: number | null;
  key_evidence_discovered: LabPair;
  key_evidence_held_by_accuser: LabPair;
  all_evidence_discovered: LabPair;
  contradictions_recognized: LabPair;
  contradictions_resolved_correctly: LabPair;
  statements: number;
  false_statements: number;
  false_ever_accepted: number;
  false_accepted_at_close: number;
  false_unrefuted_at_close: number;
  credibility_revisions: number;
  runs_where_accuser_impeached_someone: number;
  withheld_answers: number;
  withholding_noticed: number;
  runs_with_escalation: number;
  replay: { verified: number; passed: number; not_run: number };
  expectations: LabExpectation[];
}

export interface LabRunRow {
  seed: number;
  category: OutcomeCategory;
  outcome: string;
  accused?: string | null; // revealed only
  supported: boolean;
  ticks: number;
  actions: number;
  decisive_found: LabPair;
  decisive_held_by_accuser: LabPair;
  all_evidence: LabPair;
  statements: number;
  false_statements: number;
  false_ever_accepted: number;
  false_accepted_at_close: number;
  false_unrefuted_at_close: number;
  credibility_revisions: number;
  impeached_by_accuser?: string[]; // revealed only
  impeached_by_accuser_count?: number;
  events: number;
  head: string;
  replay: Record<"chain" | "fold" | "decisions" | "policies", boolean> | null;
  expectations: Record<string, boolean | null>;
  verdict: string;
}

export interface LabReasoningResult {
  category: OutcomeCategory;
  verdict: string;
  convicted?: string | null; // revealed only
  prime_suspect?: string | null; // revealed only
  beliefs: Record<string, { support: number; contra: number; status: string }>;
  suspects: Record<string, { score: number; opportunity: string; means: boolean; motive: string }>;
  credibility: Record<string, { current: { standing: string } | null }>;
  expectations: Record<string, boolean | null>;
}

export interface LabOverview {
  title: string;
  label: string;
  protocol: string[];
  categories: Record<string, string>;
  outcome_categories: OutcomeCategory[];
  registered: { engine_version: string; rules_version: string; behaviour_fingerprint: string };
  running: { engine_version: string; rules_version: string; behaviour_fingerprint: string };
  drift: string[];
  can_execute: boolean;
  stored: {
    available: boolean;
    problem: string | null;
    source: string;
    seeds: [number, number] | null;
    replay: string | null;
    registered_configuration: boolean | null;
    runs: number;
    replay_passed: number;
  };
  playable: { id: string; category: string; kind: "playable"; policies: Record<string, string>; interventions: [string, number][]; has_stored: boolean; aggregate: LabAggregate | null }[];
  reasoning: {
    id: string;
    category: string;
    kind: "reasoning";
    has_stored: boolean;
    result: { category: OutcomeCategory; verdict: string; expectations: LabExpectation[] } | null;
  }[];
  predictions: { playable: { right: number; of: number }; reasoning: { right: number; of: number } };
  wrong_predictions: { challenge: string; kind: string; expectation: string; predicted: string; observed: string; held: number; of: number }[];
  limitations: { id: string; explanation: string }[];
  notes: string[];
  execute: { max_seeds: number; policies: string; network: string };
}

export interface LabGroundTruth {
  culprit: string;
  question: string;
  prediction: string | null;
  expectations: { id: string; kind: string; says: string; predicted: string; check: string; args: Record<string, unknown> }[];
  variant_summary?: string;
  edits?: { op: string; target: string; why: string }[];
}

export interface LabChallenge {
  id: string;
  kind: "playable" | "reasoning";
  category: string;
  category_meaning: string | null;
  revealed: boolean;
  source: "stored" | null;
  stored_problem: string | null;
  can_execute: boolean;
  setup?: {
    variant: string;
    base: string;
    scenario_id: string;
    scenario_version: string;
    scenario_hash: string;
    policies: Record<string, string>;
    interventions: [string, number][];
    solvable: Record<string, string | boolean> | null;
  };
  items?: { id: string; kind: string; speaker: string | null; origin: string | null; asserts: string[] }[];
  stored: { aggregate: LabAggregate; runs: LabRunRow[] } | { result: LabReasoningResult; expectations: LabExpectation[] } | null;
  ground_truth?: LabGroundTruth;
}

export interface LabExecution {
  source: "executed";
  id: string;
  kind: "playable" | "reasoning";
  label: string;
  revealed: boolean;
  seeds: number[];
  replay: boolean;
  runs?: LabRunRow[];
  aggregate?: LabAggregate;
  result?: LabReasoningResult;
  expectations?: LabExpectation[];
  compared_with_stored: { compared: number; identical: number; different_seeds: number[] } | null;
}

export interface LabOpened {
  run: RunSummary;
  registered_interventions: { intervention_id: string; after_tick: number }[];
}

export const api = {
  scenarios: () => call<ScenarioSummary[]>("/api/scenarios"),
  runs: () => call<RunSummary[]>("/api/runs"),
  createRun: (body: { scenario_id: string; seed: number; policies: Record<string, string>; label: string }) => post<RunSummary>("/api/runs", body),
  deleteRun: (id: string) => call<void>(`/api/runs/${id}`, { method: "DELETE" }),
  snapshot: (id: string, tick: number | null) => call<Snapshot>(`/api/runs/${id}/snapshot${query({ tick })}`),
  events: (id: string, after = -1) => call<EventRow[]>(`/api/runs/${id}/events${query({ after })}`),
  graph: (id: string, tick: number | null, perspective: string) => call<GraphData>(`/api/runs/${id}/graph${query({ tick, perspective })}`),
  evaluation: (id: string) => call<Evaluation>(`/api/runs/${id}/evaluation`),
  verify: (id: string) => call<VerifyReport>(`/api/runs/${id}/verify`),
  compare: (a: string, b: string) => call<Comparison>(`/api/compare${query({ a, b })}`),
  step: (id: string, ticks: number) => post<{ run: RunSummary; events: EventRow[] }>(`/api/runs/${id}/step`, { ticks }),
  intervene: (id: string, intervention_id: string) => post<{ run: RunSummary; events: EventRow[] }>(`/api/runs/${id}/interventions`, { intervention_id }),
  setPolicy: (id: string, agent: string, policy: string) => post<{ run: RunSummary; events: EventRow[] }>(`/api/runs/${id}/policy`, { agent, policy }),
  branch: (id: string, tick: number, label: string) => post<RunSummary>(`/api/runs/${id}/branch`, { tick, label }),
  reveal: (id: string) => post<RunSummary>(`/api/runs/${id}/reveal`),
  lab: () => call<LabOverview>("/api/lab"),
  labChallenge: (id: string, reveal: boolean) => call<LabChallenge>(`/api/lab/challenges/${encodeURIComponent(id)}${query({ reveal: reveal ? "true" : null })}`),
  labExecute: (id: string, seeds: number[], replay: boolean, reveal: boolean) =>
    post<LabExecution>(`/api/lab/challenges/${encodeURIComponent(id)}/execute${query({ reveal: reveal ? "true" : null })}`, { seeds, replay }),
  labOpen: (id: string, seed: number) => post<LabOpened>(`/api/lab/challenges/${encodeURIComponent(id)}/open`, { seed }),
};
