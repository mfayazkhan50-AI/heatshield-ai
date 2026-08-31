"use client";

import {
  Activity,
  CheckCircle2,
  ChevronDown,
  Crosshair,
  Fingerprint,
  GitCommitHorizontal,
  ShieldAlert,
  ShieldCheck,
  Timer,
  AlertTriangle,
  CircleCheck,
  Stethoscope,
} from "lucide-react";
import { useMemo, useState } from "react";
import type {
  AgentOutcome,
  ConfidenceAssessment,
  DecisionEntry,
  IncidentSnapshot,
  IncidentState,
  InterventionSimulation,
  Reassessment,
  ResponseMetrics,
  RiskTier,
} from "@/lib/types";

/**
 * Operator-facing loop ordering. The last step is SETTLE — it represents
 * either an escalation or a PROJECTED settlement; genuine verification (→
 * strong RESOLVED) is reserved for a real field confirmation and is NOT in
 * the loop we run here.
 */
const LOOP_STAGES = [
  { key: "OBSERVE", label: "OBSERVE", detail: "heat + response inputs" },
  { key: "ASSESS", label: "ASSESS", detail: "gap & tier computed" },
  { key: "PLAN", label: "PLAN", detail: "intervention selected" },
  { key: "ACT", label: "ACT", detail: "action executed" },
  { key: "VERIFY", label: "VERIFY", detail: "ack window observed" },
  { key: "REASSESS", label: "REASSESS", detail: "risk re-projected" },
  { key: "SETTLE", label: "SETTLE", detail: "escalate or projected" },
] as const;

const OUTCOME_META: Record<
  AgentOutcome | "RUNNING",
  { label: string; text: string; border: string; bg: string; dot: string }
> = {
  ESCALATED: {
    label: "ESCALATED",
    text: "text-brand-critical",
    border: "border-brand-critical/50",
    bg: "bg-brand-critical/10",
    dot: "bg-brand-critical",
  },
  PROJECTED_RESOLUTION: {
    label: "PROJECTED RESOLUTION",
    text: "text-thermal-warning",
    border: "border-thermal-warning/50",
    bg: "bg-thermal-warning/10",
    dot: "bg-thermal-warning",
  },
  NO_ACTION_REQUIRED: {
    label: "NO ACTION REQUIRED",
    text: "text-thermal-low",
    border: "border-thermal-low/50",
    bg: "bg-thermal-low/10",
    dot: "bg-thermal-low",
  },
  VERIFIED: {
    label: "RESOLVED · VERIFIED",
    text: "text-brand-normal",
    border: "border-brand-normal/50",
    bg: "bg-brand-normal/10",
    dot: "bg-brand-normal",
  },
  RUNNING: {
    label: "RUNNING",
    text: "text-ink-secondary",
    border: "border-hairline",
    bg: "bg-panel-raised/40",
    dot: "bg-brand-elevated",
  },
};

function outcomeMeta(outcome?: AgentOutcome | null): typeof OUTCOME_META.ESCALATED {
  if (!outcome) return OUTCOME_META.RUNNING;
  return OUTCOME_META[outcome] ?? OUTCOME_META.RUNNING;
}

const TIER_TEXT: Record<string, string> = {
  NORMAL: "text-thermal-low",
  ELEVATED: "text-thermal-caution",
  HIGH: "text-thermal-warning",
  CRITICAL: "text-brand-critical",
};

function confidenceClass(level?: ConfidenceAssessment["level"]): string {
  if (level === "HIGH") return "text-brand-normal";
  if (level === "MODERATE") return "text-thermal-warning";
  return "text-brand-critical";
}

const CONFIDENCE_BADGE: Record<string, { text: string; border: string; bg: string }> = {
  HIGH: { text: "text-brand-normal", border: "border-brand-normal/40", bg: "bg-brand-normal/10" },
  MODERATE: { text: "text-thermal-warning", border: "border-thermal-warning/40", bg: "bg-thermal-warning/10" },
  LOW: { text: "text-brand-critical", border: "border-brand-critical/40", bg: "bg-brand-critical/10" },
};

function stateBadge(state?: IncidentState): { label: string; cls: string } {
  const map: Record<string, { label: string; cls: string }> = {
    DETECTED: { label: "DETECTED", cls: "border-hairline bg-panel-raised/40 text-ink-secondary" },
    ASSESSING: { label: "ASSESSING", cls: "border-thermal-caution/40 bg-thermal-caution/10 text-thermal-caution" },
    PLANNED: { label: "PLANNED", cls: "border-thermal-caution/40 bg-thermal-caution/10 text-thermal-caution" },
    ACTING: { label: "ACTING", cls: "border-thermal-warning/40 bg-thermal-warning/10 text-thermal-warning" },
    WAITING_FOR_ACK: { label: "WAITING FOR ACK", cls: "border-thermal-warning/40 bg-thermal-warning/10 text-thermal-warning" },
    ACK_TIMED_OUT: { label: "ACK TIMED OUT", cls: "border-brand-critical/40 bg-brand-critical/10 text-brand-critical" },
    ACKNOWLEDGED: { label: "ACKNOWLEDGED", cls: "border-brand-normal/40 bg-brand-normal/10 text-brand-normal" },
    VERIFYING: { label: "FIELD VERIFICATION REQUIRED", cls: "border-thermal-warning/40 bg-thermal-warning/10 text-thermal-warning" },
    ESCALATED: { label: "ESCALATED", cls: "border-brand-critical/40 bg-brand-critical/10 text-brand-critical" },
    RESOLVED: { label: "RESOLVED", cls: "border-brand-normal/40 bg-brand-normal/10 text-brand-normal" },
  };
  return map[state ?? ""] ?? { label: state ?? "—", cls: "border-hairline text-ink-muted" };
}

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1) return "<1ms";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

/**
 * ClosedLoopPanel — the "Agent Control Tower" hero.
 *
 * Surfaces the closed-loop decision story in operator terms: a P0-P5 risk
 * strip, the live agent loop, the deterministic before/after projection with
 * its dynamic % impact, an operator-friendly "Why This Action", and the
 * technical/audit trace collapsed by default. Every value is authoritative
 * server state; nothing is overclaimed — PROJECTED vs VERIFIED semantics are
 * respected (VERIFIED is reserved for genuine field confirmation).
 */
export default function ClosedLoopPanel({
  incidentId,
  agentOutcome,
  incident,
  confidence,
  decisionTrace,
  simulations,
  selected,
  reassessment,
  metrics,
  heatIndexF,
  riskTier,
  responseGap,
}: {
  incidentId?: string | null;
  agentOutcome?: AgentOutcome | null;
  incident?: IncidentSnapshot | null;
  confidence?: ConfidenceAssessment | null;
  decisionTrace?: DecisionEntry[];
  simulations?: InterventionSimulation[];
  selected?: InterventionSimulation | null;
  reassessment?: Reassessment | null;
  metrics?: ResponseMetrics | null;
  heatIndexF?: number | null;
  riskTier?: RiskTier | null;
  responseGap?: number | null;
}) {
  const [openTrace, setOpenTrace] = useState(false);
  const [openHow, setOpenHow] = useState(false);

  const trace = useMemo(() => decisionTrace ?? [], [decisionTrace]);
  const stagesDone = useMemo(() => new Set(trace.map((d) => d.stage)), [trace]);
  const lastDecision = trace[trace.length - 1];

  const meta = outcomeMeta(agentOutcome);
  const sb = stateBadge(incident?.state);
  const projected = reassessment;
  const simulated = selected;

  const pctImprovement = useMemo(() => {
    if (!projected || !projected.before_response_gap) return null;
    const raw =
      ((projected.before_response_gap - projected.after_response_gap) /
        projected.before_response_gap) *
      100;
    return Math.max(0, Math.round(raw));
  }, [projected]);

  // Operator-friendly "Why This Action" — plain language, decision + drivers
  // + confidence/source. Falls back gracefully to raw server reason.
  const whyTitle = useMemo(
    () =>
      agentOutcome === "ESCALATED"
        ? "Escalated for human review"
        : agentOutcome === "PROJECTED_RESOLUTION"
          ? "Projected to clear the risk threshold"
          : lastDecision?.action ?? "No intervention modeled",
    [agentOutcome, lastDecision],
  );

  const whyReason = useMemo(() => {
    if (agentOutcome === "ESCALATED") {
      const first =
        incident?.escalation_reasons?.[0] ??
        lastDecision?.reason ??
        "insufficient information to claim a safe outcome from one pass";
      return `The agent could not project a safe outcome and flagged this for a human supervisor. ${first}`;
    }
    if (agentOutcome === "PROJECTED_RESOLUTION") {
      return lastDecision?.reason ??
        `Projected response gap ${projected?.before_response_gap?.toFixed(2)} → ${projected?.after_response_gap?.toFixed(2)}. This is a projection — field verification is still required.`;
    }
    if (agentOutcome === "NO_ACTION_REQUIRED") {
      return lastDecision?.reason ?? "No elevated heat risk was detected; no intervention is required.";
    }
    return lastDecision?.reason ?? "No decision recorded yet.";
  }, [agentOutcome, incident, lastDecision, projected]);

  const drivers = useMemo(() => {
    if (!simulated || !simulated.after) return null;
    const before = simulated.before?.risk_tier;
    const after = simulated.after?.risk_tier;
    const parts: string[] = [];
    if (before && after && before !== after)
      parts.push(`risk tier ${before} → ${after}`);
    if (projected?.projected_delta != null && projected.projected_delta > 0)
      parts.push(`response gap −${projected.projected_delta.toFixed(2)}`);
    if (confidence?.level)
      parts.push(`confidence ${confidence.level}`);
    return parts;
  }, [simulated, projected, confidence]);

  if (!incidentId && !incident && !trace.length) return null;

  return (
    <section className="overflow-hidden rounded-xl border border-hairline bg-panel/70">
      {/* ================================================ header: control tower */}
      <header className="flex flex-wrap items-center gap-2 border-b border-hairline bg-panel-raised/30 px-4 py-3">
        <div className="flex h-7 w-7 items-center justify-center rounded border border-brand-elevated/40 bg-brand-elevated/10">
          <Crosshair size={14} className="text-brand-elevated" />
        </div>
        <div className="min-w-0">
          <h3 className="font-mono text-[11px] font-bold uppercase tracking-[0.18em] text-ink-primary">
            Agent Control Tower
          </h3>
          <p className="flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-wider text-ink-muted">
            <Fingerprint size={9} />
            <span className="truncate">
              {incidentId ?? incident?.incident_id ?? "inc-…"}
            </span>
          </p>
        </div>
        <span
          className={`ml-auto flex items-center gap-1.5 rounded border px-2 py-1 font-mono text-[9px] font-semibold uppercase tracking-wider ${meta.border} ${meta.bg} ${meta.text}`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${meta.dot} ${!agentOutcome ? "animate-pulse_soft" : ""}`} />
          {meta.label}
        </span>
      </header>

      {/* ================================================ P0-P5 risk story strip */}
      <div className="grid grid-cols-2 divide-x divide-hairline/70 border-b border-hairline sm:grid-cols-5">
        {/* P0 heat index */}
        <div className="px-3 py-2.5">
          <div className="font-mono text-[8.5px] uppercase tracking-widest text-ink-muted">P0 · Heat Index</div>
          <div className="mt-0.5 font-mono text-lg font-bold leading-none text-ink-primary">
            {heatIndexF != null ? `${Math.round(heatIndexF)}°F` : "—"}
          </div>
        </div>
        {/* P1 response gap */}
        <div className="px-3 py-2.5">
          <div className="font-mono text-[8.5px] uppercase tracking-widest text-ink-muted">P1 · Response Gap</div>
          <div className={`mt-0.5 font-mono text-lg font-bold leading-none ${riskTier ? TIER_TEXT[riskTier] ?? "text-ink-primary" : "text-ink-primary"}`}>
            {responseGap != null ? responseGap.toFixed(2) : "—"}
          </div>
          <div className="mt-0.5 font-mono text-[9px] uppercase tracking-wide text-ink-muted">
            {riskTier ?? "tier"}
          </div>
        </div>
        {/* P2 agent status */}
        <div className="px-3 py-2.5">
          <div className="font-mono text-[8.5px] uppercase tracking-widest text-ink-muted">P2 · Agent Status</div>
          <span className={`mt-1 inline-block rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide ${sb.cls}`}>
            {sb.label}
          </span>
        </div>
        {/* P3 agent decision */}
        <div className="px-3 py-2.5">
          <div className="font-mono text-[8.5px] uppercase tracking-widest text-ink-muted">P3 · Decision</div>
          <div className={`mt-1 font-mono text-[10px] font-semibold uppercase leading-tight ${meta.text}`}>
            {simulated?.title ?? lastDecision?.action ?? "awaiting run"}
          </div>
        </div>
        {/* P4-P5 projected impact */}
        <div className="px-3 py-2.5">
          <div className="font-mono text-[8.5px] uppercase tracking-widest text-ink-muted">P4·P5 · Impact</div>
          <div className="mt-1 font-mono text-lg font-bold leading-none text-thermal-warning">
            {pctImprovement != null ? `−${pctImprovement}%` : "—"}
          </div>
          <div className="mt-0.5 font-mono text-[8.5px] uppercase tracking-wide text-ink-muted">
            projected ΔR
          </div>
        </div>
      </div>

      {/* ================================================ agent loop (vertical) */}
      <div className="border-b border-hairline px-4 py-3">
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-widest text-ink-secondary">
            <Activity size={11} /> Agent Loop
          </div>
          {confidence && (
            <span className={`rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide ${CONFIDENCE_BADGE[confidence.level]?.border} ${CONFIDENCE_BADGE[confidence.level]?.bg} ${CONFIDENCE_BADGE[confidence.level]?.text}`}>
              confidence {confidence.level} · {confidence.source}
            </span>
          )}
        </div>

        <ol className="space-y-1">
          {LOOP_STAGES.map((stage, i) => {
            const done = stagesDone.has(stage.key as DecisionEntry["stage"]);
            const terminal = stage.key === "SETTLE";
            const active = lastDecision?.stage === stage.key;
            return (
              <li key={stage.key} className="flex items-start gap-3">
                <div className="flex flex-col items-center">
                  <span
                    className={`flex h-4 w-4 items-center justify-center rounded-full border font-mono text-[7px] ${
                      active
                        ? "border-brand-elevated/60 bg-brand-elevated/20 text-brand-elevated"
                        : done
                          ? terminal && agentOutcome === "ESCALATED"
                            ? "border-brand-critical/50 bg-brand-critical/15 text-brand-critical"
                            : done
                              ? "border-brand-normal/50 bg-brand-normal/15 text-brand-normal"
                              : "border-hairline bg-panel-raised/40 text-ink-muted"
                          : "border-hairline bg-panel-raised/40 text-ink-muted"
                    }`}
                  >
                    {done ? <CheckCircle2 size={9} /> : i + 1}
                  </span>
                  {i < LOOP_STAGES.length - 1 && (
                    <span
                      className={`my-0.5 w-px flex-1 ${done ? "bg-brand-normal/40" : "bg-hairline/70"}`}
                    />
                  )}
                </div>
                <div className="min-w-0 flex-1 pb-1.5">
                  <div className="flex items-baseline gap-2">
                    <span
                      className={`font-mono text-[10px] font-bold uppercase tracking-wider ${
                        active
                          ? "text-brand-elevated"
                          : done
                            ? terminal && agentOutcome === "ESCALATED"
                              ? "text-brand-critical"
                              : "text-brand-normal"
                            : "text-ink-muted"
                      }`}
                    >
                      {stage.label}
                    </span>
                    <span className="hidden font-mono text-[9px] text-ink-muted sm:inline">
                      {stage.detail}
                    </span>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>

        {/* WAITING FOR ACK context */}
        {incident?.state === "WAITING_FOR_ACK" && (
          <div className="mt-2 rounded border border-thermal-warning/40 bg-thermal-warning/10 px-2.5 py-1.5 font-mono text-[9px] uppercase tracking-wide text-thermal-warning">
            waiting for ack · window {incident.ack_window_s}s
            {incident.ack_overdue ? " · OVERDUE →" : ""}
          </div>
        )}
        {incident?.state === "ACK_TIMED_OUT" && (
          <div className="mt-2 rounded border border-brand-critical/40 bg-brand-critical/10 px-2.5 py-1.5 font-mono text-[9px] uppercase tracking-wide text-brand-critical">
            ack window elapsed — supervisor dispatch triggered
          </div>
        )}
      </div>

      {/* ================================================ projection + why */}
      {(simulated || projected) && (
        <div className="border-b border-hairline px-4 py-3">
          <div className="mb-2 flex items-start justify-between gap-2">
            <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-widest text-ink-secondary">
              <GitCommitHorizontal size={11} /> Projected after action
            </div>
            <span className="rounded border border-thermal-warning/40 bg-thermal-warning/10 px-1.5 py-0.5 font-mono text-[8px] uppercase tracking-wider text-thermal-warning">
              projected — field verification required
            </span>
          </div>

          {/* before → after */}
          <div className="flex items-end gap-3">
            <div>
              <div className="font-mono text-[9px] uppercase text-ink-muted">Before</div>
              <div className="font-mono text-2xl font-bold leading-none text-thermal-warning">
                {projected?.before_response_gap?.toFixed(2) ?? simulated?.before?.response_gap?.toFixed(2) ?? "—"}
              </div>
              <div className="font-mono text-[9px] uppercase text-ink-muted">
                {projected?.before_risk_tier ?? simulated?.before?.risk_tier ?? ""}
              </div>
            </div>

            <span className="mb-1 flex items-center gap-1 font-mono text-[10px] text-ink-muted">
              →
            </span>

            <div>
              <div className="font-mono text-[9px] uppercase text-ink-muted">After (projected)</div>
              <div className="font-mono text-2xl font-bold leading-none text-brand-normal">
                {projected?.after_response_gap?.toFixed(2) ?? simulated?.after?.response_gap?.toFixed(2) ?? "—"}
              </div>
              <div className="font-mono text-[9px] uppercase text-ink-muted">
                {projected?.after_risk_tier ?? simulated?.after?.risk_tier ?? ""}
              </div>
            </div>

            <div className="ml-auto text-right">
              <div className="font-mono text-[9px] uppercase text-ink-muted">Δ gap impact</div>
              <div className="font-mono text-xl font-bold leading-none text-thermal-warning">
                {pctImprovement != null ? `−${pctImprovement}%` : "—"}
              </div>
              <div className="mt-0.5 font-mono text-[8.5px] uppercase text-ink-muted">
                clears {projected?.dispatch_threshold?.toFixed(1) ?? "—"}?{" "}
                {projected?.mitigated_below_threshold ? (
                  <span className="text-brand-normal">yes</span>
                ) : (
                  <span className="text-brand-critical">no</span>
                )}
              </div>
            </div>
          </div>

          {/* Why this action */}
          <button
            type="button"
            onClick={() => setOpenHow((v) => !v)}
            className="mt-3 flex w-full items-center gap-2 rounded border border-hairline bg-panel-raised/30 px-3 py-2 text-left transition hover:border-brand-elevated/40"
          >
            <Stethoscope size={13} className="shrink-0 text-brand-elevated" />
            <span className="min-w-0 flex-1">
              <span className="block font-mono text-[10px] uppercase tracking-widest text-ink-secondary">
                Why this action
              </span>
              <span className="block truncate text-[11px] font-semibold text-ink-primary">
                {whyTitle}
              </span>
            </span>
            <ChevronDown
              size={14}
              className={`shrink-0 text-ink-muted transition-transform ${openHow ? "rotate-180" : ""}`}
            />
          </button>

          {openHow && (
            <div className="mt-2 space-y-2 rounded border border-hairline bg-panel-raised/30 p-3">
              <p className="text-xs leading-relaxed text-ink-secondary">{whyReason}</p>

              {simulated && (
                <div className="flex items-start gap-2 border-t border-hairline pt-2">
                  <ShieldAlert size={13} className="mt-0.5 shrink-0 text-brand-elevated" />
                  <div className="min-w-0 flex-1">
                    <p className="font-mono text-[10px] font-semibold uppercase tracking-wide text-ink-primary">
                      {simulated.title}
                    </p>
                    <p className="mt-0.5 text-[11px] leading-relaxed text-ink-secondary">
                      {simulated.message}
                    </p>
                    <div className="mt-1.5 flex flex-wrap gap-1.5 font-mono text-[9px] uppercase text-ink-muted">
                      <span className="rounded border border-hairline px-1.5 py-0.5">cost {simulated.resource.cost}</span>
                      <span className="rounded border border-hairline px-1.5 py-0.5">eta {simulated.resource.eta_min}m</span>
                      <span className="rounded border border-hairline px-1.5 py-0.5">staff {simulated.resource.staff}</span>
                      <span className="rounded border border-thermal-warning/30 bg-thermal-warning/10 px-1.5 py-0.5 text-thermal-warning">status projected</span>
                    </div>
                  </div>
                </div>
              )}

              {drivers && drivers.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5 border-t border-hairline pt-2">
                  <span className="font-mono text-[9px] uppercase tracking-wide text-ink-muted">drivers</span>
                  {drivers.map((d) => (
                    <span key={d} className="rounded border border-hairline px-1.5 py-0.5 font-mono text-[9px] uppercase text-ink-secondary">
                      {d}
                    </span>
                  ))}
                </div>
              )}

              {confidence && (
                <div className="border-t border-hairline pt-2 font-mono text-[9px] text-ink-muted">
                  <span className="uppercase tracking-wide">confidence</span>{" "}
                  <span className={confidenceClass(confidence.level)}>{confidence.level}</span> ·{" "}
                  <span>{confidence.model}</span> · source <span>{confidence.source}</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ================================================ collapsed decision trace */}
      {trace.length > 0 && (
        <details className="group">
          <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-2.5 transition-colors hover:bg-panel-raised/30 [&::-webkit-details-marker]:hidden">
            <ShieldCheck size={13} className="shrink-0 text-ink-secondary" />
            <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-ink-secondary">
              Decision trace & audit
            </span>
            <span className="ml-auto font-mono text-[9px] text-ink-muted">
              {trace.length} steps · technical
            </span>
            <ChevronDown size={13} className="text-ink-muted transition-transform group-open:rotate-180" />
          </summary>

          <div className="border-t border-hairline">
            <ol className="divide-y divide-hairline/70">
              {trace.map((d) => (
                <li key={d.id} className="flex gap-3 px-4 py-2.5">
                  <span className="mt-0.5 w-20 shrink-0 font-mono text-[10px] font-semibold uppercase text-brand-elevated">
                    {d.stage}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold text-ink-primary">{d.action}</p>
                    <p className="mt-0.5 text-[11px] leading-relaxed text-ink-secondary">{d.reason}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-2 font-mono text-[9px] text-ink-muted">
                      <span>{d.id}</span>
                      <span>·</span>
                      <span className={confidenceClass(d.confidence?.level)}>
                        {d.confidence?.level ?? "—"}
                      </span>
                      <span>·</span>
                      <span>{d.strategy}</span>
                    </div>
                  </div>
                </li>
              ))}
            </ol>

            {/* response metrics */}
            {metrics && (
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-hairline/70 bg-panel-raised/20 px-4 py-2.5 font-mono text-[9px] text-ink-secondary">
                <span className="flex items-center gap-1 text-ink-muted"><Timer size={10} /> response</span>
                <span>detect→assess {fmtMs(metrics.detect_ms)}</span>
                <span>assess→plan {fmtMs(metrics.assess_ms)}</span>
                <span>plan→act {fmtMs(metrics.plan_ms)}</span>
                <span className="text-ink-primary">detect→act {fmtMs(metrics.detect_to_act_ms)}</span>
              </div>
            )}
          </div>
        </details>
      )}

      {/* ================================================ footer honesty note */}
      {(simulated || projected) && (
        <div className="flex items-start gap-2 border-t border-hairline bg-panel-raised/20 px-4 py-2.5">
          {agentOutcome === "ESCALATED" ? (
            <AlertTriangle size={12} className="mt-0.5 shrink-0 text-brand-critical" />
          ) : (
            <CircleCheck size={12} className="mt-0.5 shrink-0 text-thermal-warning" />
          )}
          <p className="font-mono text-[9px] uppercase leading-relaxed tracking-wide text-ink-muted">
            {agentOutcome === "ESCALATED"
              ? "Escalated — awaiting human supervisor; no resolution claimed."
              : "Outcome is projected from simulated action — a real field confirmation is required before this is treated as verified."}
          </p>
        </div>
      )}
    </section>
  );
}
