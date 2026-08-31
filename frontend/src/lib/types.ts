/**
 * Wire contracts for HeatShield AI v2 — mirrors backend/app/state.py.
 */

// ---------------------------------------------------------------------------
// Deterministic scoring artifact (engine/scoring.py output)
// ---------------------------------------------------------------------------

export interface ScoreSubInput {
  key: string;
  label: string;
  value: number;
  sub_weight: number;
  anchor: string;
}

export interface ScoreComponent {
  key: string;
  label: string;
  value: number;
  weight: number;
  contribution: number;
  method: string;
  subs: ScoreSubInput[];
  effective_inputs?: Record<string, unknown>;
}

export type RiskTier = "NORMAL" | "ELEVATED" | "HIGH" | "CRITICAL";

export interface RiskBreakdown {
  schema_version: string;
  engine: string;
  response_gap: number;
  risk_tier: RiskTier;
  dispatch_eligible: boolean;
  dispatch_threshold: number;
  formula_expression: string;
  formula_substitution: string;
  components: ScoreComponent[];
  raw_inputs: Record<string, number | string>;
  operation_profile: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Agent run payload
// ---------------------------------------------------------------------------

export interface TacticalAction {
  id: string;
  title: string;
  detail: string;
  horizon: string;
  source: string;
}

export interface DispatchRecord {
  activity_id: string;
  to: string;
  site: string;
  channel: "sms" | "voice";
  mode: "live" | "dry_run";
  status: string;
  preview?: string | null;
  provider_ref?: string | null;
  error?: string | null;
  ts: string;
}

export type OperationContext = "construction" | "delivery" | "roadwork";

/** Every provider Tier-4 BYOK accepts. Hosted tiers stay groq+gemini. */
export type LlmProvider =
  | "groq"
  | "gemini"
  | "openai"
  | "anthropic"
  | "deepseek";

export interface CompliancePlan {
  risk_level: string;
  heat_index_f: number;
  work_rest_cycle: string;
  hydration_benchmark: string;
  monitoring_indicators: string[];
  mandatory_ppe: string[];
  escalation_protocol: string;
  generated_by_tier: string;
}

export type FieldSource = "live" | "cached" | "simulated" | "deterministic_fallback";

export interface EnterpriseOutput {
  location_name: string;
  latitude: number;
  longitude: number;
  observed_at: string;
  activity_id: string | null;
  operation_context: OperationContext;
  heat_index_f: number;
  risk_level: string;
  risk_breakdown: RiskBreakdown | null;
  compliance_plan: CompliancePlan;
  tactical_actions: TacticalAction[];
  dispatch_records: DispatchRecord[];
  dispatch_mode: "live" | "dry_run" | "not_triggered";
  active_tier: string;
  tier_trace: string[];
  source: FieldSource;
  provenance?: string | null;
  fallback_reason?: string | null;
  // Closed-loop agent artifacts (also promoted to AgentResponse top-level)
  incident_id?: string | null;
  agent_outcome?: "RESOLVED" | "ESCALATED" | null;
  confidence?: ConfidenceAssessment | null;
  decision_trace?: DecisionEntry[];
  response_metrics?: ResponseMetrics | null;
}

/** Final SSE `result` event payload, cacheable per site. */
export interface AgentResponse {
  enterprise_output: EnterpriseOutput | null;
  risk_breakdown?: RiskBreakdown | null;
  tactical_actions?: TacticalAction[];
  dispatch_records?: DispatchRecord[];
  dispatch_mode?: EnterpriseOutput["dispatch_mode"];
  activity_id?: string | null;
  awaiting_byok: boolean;
  active_tier: string | null;
  tier_trace: string[];
  node_log: Array<Record<string, unknown>>;
  // Closed-loop agent artifacts (P0)
  incident_id?: string | null;
  agent_outcome?: "RESOLVED" | "ESCALATED" | null;
  incident?: IncidentSnapshot | null;
  confidence?: ConfidenceAssessment | null;
  decision_trace?: DecisionEntry[];
  intervention_simulations?: InterventionSimulation[];
  selected_intervention?: InterventionSimulation | null;
  reassessment?: Reassessment | null;
  response_metrics?: ResponseMetrics | null;
}

// ---------------------------------------------------------------------------
// Closed-loop agent contracts (mirrors backend/app/{engine,services}/P0)
// ---------------------------------------------------------------------------

export type IncidentState =
  | "DETECTED" | "ASSESSING" | "PLANNED" | "ACTING"
  | "WAITING_FOR_ACK" | "ACKNOWLEDGED" | "ACK_TIMED_OUT"
  | "ESCALATING" | "ESCALATED" | "VERIFYING" | "RESOLVED";

export interface IncidentEntry {
  state: IncidentState;
  action: string;
  detail: string;
  ts: string;
}

export interface IncidentSnapshot {
  incident_id: string;
  site: string;
  activity_id: string;
  state: IncidentState;
  ack_window_s: number;
  created_at_iso: string;
  acknowledged_at_iso?: string | null;
  acknowledged_by?: string | null;
  ack_overdue: boolean;
  escalation_tier: string;
  escalation_reasons: string[];
  resolution_note?: string | null;
  entries: IncidentEntry[];
}

export interface ConfidenceAssessment {
  level: "HIGH" | "MODERATE" | "LOW";
  model: string;
  source: string;
  reasons: string[];
  missing_inputs: string[];
  is_high_confidence: boolean;
  note: string;
}

export interface DecisionEntry {
  id: string;
  stage:
    | "OBSERVE" | "ASSESS" | "PLAN" | "ACT" | "VERIFY"
    | "REASSESS" | "ESCALATE" | "RESOLVE";
  action: string;
  reason: string;
  strategy: string;
  confidence: ConfidenceAssessment;
  state_before: Record<string, unknown>;
  ts: string;
}

export interface InterventionSimulation {
  key: string;
  title: string;
  message: string;
  status: "projected";
  effective: boolean;
  before: { response_gap: number; risk_tier: RiskTier };
  after: { response_gap: number; risk_tier: RiskTier };
  prospective_delta: number;
  prospective_improvement: number;
  projected_inputs: Record<string, number>;
  resource: { cost: string; eta_min: number; staff: number };
}

export interface Reassessment {
  before_response_gap: number;
  before_risk_tier: RiskTier;
  after_response_gap: number;
  after_risk_tier: RiskTier;
  projected_delta: number;
  mitigated_below_threshold: boolean;
  dispatch_threshold: number;
  projected: boolean;
}

export interface ResponseMetrics {
  detect_ms: number | null;
  assess_ms: number | null;
  plan_ms: number | null;
  detect_to_act_ms: number | null;
}

/**
 * Exact request parameters captured at trigger time and passed verbatim
 * into the POST request body — the single source of truth for a run.
 */
export interface AgentStreamParams {
  thread_id: string;
  location_name: string;
  latitude: number;
  longitude: number;
  operation_context: OperationContext;
  byok_provider?: LlmProvider;
  byok_key?: string;
}

// ---------------------------------------------------------------------------
// NDJSON heatmap stream
// ---------------------------------------------------------------------------

export interface HeatCell {
  lat: number;
  lon: number;
  temp_f: number;
  temp_c: number;
  intensity: number;
  class: "SAFE" | "WARM" | "HOT" | "CRITICAL";
}

export interface HeatmapResultPayload {
  activity_id: string;
  location_name: string;
  latitude: number;
  longitude: number;
  operation_context: OperationContext;
  source: "live" | "simulated";
  fallback_reason: string | null;
  provenance?: string | null;
  observed_at?: string | null;
  peak_temp_f: number;
  peak_temp_c: number;
  critical_cells: number;
  tile_count: number;
  consecutive_hours_above_40c: number;
  osha_bin: string;
  risk_breakdown: RiskBreakdown;
  generated_at: string;
  cache?: { hit: boolean; lookup_ms?: number };
  latency_ms?: number;
  cells?: HeatCell[];
}

export interface PollProgress {
  status: "polling";
  attempt: number;
  max: number;
  pct?: number;
  elapsed_ms: number;
  deadline_s?: number;
}

export type HeatmapConnState =
  | "idle"
  | "connecting"
  | "streaming"
  | "done"
  | "error";

// ---------------------------------------------------------------------------
// UI bookkeeping
// ---------------------------------------------------------------------------

export type NodePhase = "idle" | "running" | "completed";

export type ConnState = "idle" | "connecting" | "streaming" | "done" | "error";

export interface LogLine {
  id: string;
  text: string;
  kind: "status" | "node" | "token" | "error";
}

/** Everything needed to instantly re-render a previously-run site. */
export interface CachedRun {
  response: AgentResponse;
  nodePhases: Record<string, NodePhase>;
  log: LogLine[];
  tokenTrace: string;
  rawResultJson: string | null;
  completedAt: string;
}

export interface AgentRunSummary {
  params: AgentStreamParams;
  response: AgentResponse;
  nodePhases: Record<string, NodePhase>;
  log: LogLine[];
  tokenTrace: string;
  rawResultJson: string | null;
}
