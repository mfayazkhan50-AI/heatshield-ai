"use client";

import {
  Activity,
  CheckCircle2,
  ChevronDown,
  GitBranch,
  ShieldAlert,
  ShieldCheck,
  Timer,
  Fingerprint,
} from "lucide-react";
import { useMemo, useState } from "react";
import type {
  ConfidenceAssessment,
  DecisionEntry,
  IncidentSnapshot,
  IncidentState,
  InterventionSimulation,
  Reassessment,
  ResponseMetrics,
} from "@/lib/types";

const STAGE_ORDER: DecisionEntry["stage"][] = [
  "OBSERVE",
  "ASSESS",
  "PLAN",
  "ACT",
  "VERIFY",
  "REASSESS",
  "ESCALATE",
  "RESOLVE",
];

function outcomeColor(outcome?: string | null): string {
  return outcome === "ESCALATED" ? "text-brand-critical" : "text-brand-normal";
}

function outcomeBadgeClass(outcome?: string | null): string {
  return outcome === "ESCALATED"
    ? "border-brand-critical/40 bg-brand-critical/10 text-brand-critical"
    : "border-brand-normal/40 bg-brand-normal/10 text-brand-normal";
}

function confidenceClass(level?: ConfidenceAssessment["level"]): string {
  if (level === "HIGH") return "text-brand-normal";
  if (level === "MODERATE") return "text-thermal-warning";
  return "text-brand-critical";
}

function stateBadge(state?: IncidentState): {
  label: string;
  cls: string;
} {
  const map: Record<string, { label: string; cls: string }> = {
    DETECTED: { label: "DETECTED", cls: "border-hairline bg-panel-raised/40 text-ink-secondary" },
    ASSESSING: { label: "ASSESSING", cls: "border-thermal-caution/40 bg-thermal-caution/10 text-thermal-caution" },
    PLANNED: { label: "PLANNED", cls: "border-thermal-caution/40 bg-thermal-caution/10 text-thermal-caution" },
    ACTING: { label: "ACTING", cls: "border-thermal-warning/40 bg-thermal-warning/10 text-thermal-warning" },
    WAITING_FOR_ACK: { label: "WAITING FOR ACK", cls: "border-thermal-warning/40 bg-thermal-warning/10 text-thermal-warning" },
    ACK_TIMED_OUT: { label: "ACK TIMED OUT", cls: "border-brand-critical/40 bg-brand-critical/10 text-brand-critical" },
    ACKNOWLEDGED: { label: "ACKNOWLEDGED", cls: "border-brand-normal/40 bg-brand-normal/10 text-brand-normal" },
    VERIFYING: { label: "VERIFYING", cls: "border-thermal-warning/40 bg-thermal-warning/10 text-thermal-warning" },
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
 * ClosedLoopPanel — the "Agent Control Tower + Incident Driver".
 *
 * Renders the P0 closed-loop lifecycle: OBSERVE->ASSESS->PLAN->ACT->VERIFY->
 * REASSESS->ESCALATE/RESOLVE, the deterministic before/after intervention
 * projection, "Why This Action", per-stage confidence, the audit decision
 * trace and response metrics. Every value is authoritative server state that
 * the agent itself marked PROJECTED vs observed — nothing overclaimed here.
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
}: {
  incidentId?: string | null;
  agentOutcome?: "RESOLVED" | "ESCALATED" | null;
  incident?: IncidentSnapshot | null;
  confidence?: ConfidenceAssessment | null;
  decisionTrace?: DecisionEntry[];
  simulations?: InterventionSimulation[];
  selected?: InterventionSimulation | null;
  reassessment?: Reassessment | null;
  metrics?: ResponseMetrics | null;
}) {
  const [openTrace, setOpenTrace] = useState(true);

  const trace = useMemo(() => decisionTrace ?? [], [decisionTrace]);
  const stagesDone = useMemo(
    () => new Set(trace.map((d) => d.stage)),
    [trace],
  );
  const lastDecision = trace[trace.length - 1];
  const why =
    lastDecision?.reason ??
    selected?.message ??
    incident?.resolution_note ??
    reassessment?.projected_delta != null
      ? `Projected ΔR ${reassessment!.projected_delta} — project-only, awaiting verification.`
      : "No intervention modeled.";

  if (!incidentId && !incident && !trace.length) return null;

  const sb = stateBadge(incident?.state);

  return (
    <section className="space-y-3">
      {/* ------------------------------------------------ driver header */}
      <div className="rounded-lg border border-hairline bg-panel/70">
        <header className="flex flex-wrap items-center gap-2 border-b border-hairline px-4 py-2.5">
          <Activity size={14} className="text-ink-secondary" />
          <h3 className="font-mono text-[11px] font-semibold uppercase tracking-widest text-ink-secondary">
            Closed-Loop Agent · Incident Driver
          </h3>
          <span
            className={`ml-auto rounded border px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide ${outcomeBadgeClass(
              agentOutcome,
            )}`}
          >
            {agentOutcome ?? "RUNNING"}
          </span>
        </header>

        <div className="grid gap-3 px-4 py-3 sm:grid-cols-2">
          {/* left: state + confidence */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className={`rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wide ${sb.cls}`}>
                {sb.label}
              </span>
              {incident?.escalation_tier && incident.escalation_tier !== "none" && (
                <span className="rounded border border-brand-critical/40 bg-brand-critical/10 px-1.5 py-0.5 font-mono text-[10px] uppercase text-brand-critical">
                  tier: {incident.escalation_tier}
                </span>
              )}
            </div>

            <div className="flex items-center gap-2 font-mono text-[10px] text-ink-muted">
              <Fingerprint size={12} />
              <span className="truncate">{incidentId ?? incident?.incident_id ?? "inc-…"}</span>
            </div>

            {confidence ? (
              <div className="flex items-center gap-2">
                <ShieldCheck size={13} className={confidenceClass(confidence.level)} />
                <span
                  className={`font-mono text-[11px] font-semibold uppercase ${confidenceClass(
                    confidence.level,
                  )}`}
                >
                  confidence: {confidence.level}
                </span>
              </div>
            ) : null}
          </div>

          {/* right: response metrics */}
          {metrics ? (
            <div className="rounded border border-hairline bg-panel-raised/40 p-2 font-mono text-[10px] text-ink-secondary">
              <div className="mb-1 flex items-center gap-1.5 text-ink-muted">
                <Timer size={11} /> RESPONSE METRICS
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                <span>detect→assess</span><span className="text-right text-ink-primary">{fmtMs(metrics.detect_ms)}</span>
                <span>assess→plan</span><span className="text-right text-ink-primary">{fmtMs(metrics.assess_ms)}</span>
                <span>plan→act</span><span className="text-right text-ink-primary">{fmtMs(metrics.plan_ms)}</span>
                <span>detect→act</span><span className="text-right text-ink-primary">{fmtMs(metrics.detect_to_act_ms)}</span>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {/* ------------------------------------------------ closed-loop stage strip */}
      {trace.length > 0 && (
        <div className="rounded-lg border border-hairline bg-panel/60 p-3">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-widest text-ink-muted">
            Agent Loop
          </div>
          <ol className="flex flex-wrap gap-1.5">
            {STAGE_ORDER.map((stage) => {
              const done = stagesDone.has(stage);
              const terminal = stage === "ESCALATE" || stage === "RESOLVE";
              const active = lastDecision?.stage === stage;
              return (
                <li
                  key={stage}
                  className={`rounded border px-2 py-1 font-mono text-[10px] ${
                    active
                      ? "border-thermal-warning/50 bg-thermal-warning/15 text-thermal-warning"
                      : done
                        ? terminal
                          ? "border-brand-normal/40 bg-brand-normal/10 text-brand-normal"
                          : "border-brand-normal/30 bg-brand-normal/[0.07] text-brand-normal"
                        : "border-hairline bg-panel-raised/30 text-ink-muted"
                  }`}
                >
                  {stage}
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {/* ------------------------------------------------ before / after + why */}
      {(selected || reassessment) && (
        <div className="rounded-lg border border-hairline bg-panel/60 p-3 sm:p-4">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-widest text-ink-muted">
            Intervention Projection (PROJECTED — not measured)
          </div>

          {reassessment && (
            <div className="mb-3 flex items-end gap-4 rounded border border-hairline bg-panel-raised/40 p-3">
              <div>
                <div className="font-mono text-[9px] uppercase text-ink-muted">Before</div>
                <div className="font-mono text-xl font-bold text-thermal-warning">
                  {reassessment.before_response_gap.toFixed(2)}
                </div>
                <div className="font-mono text-[10px] text-ink-secondary">
                  {reassessment.before_risk_tier}
                </div>
              </div>
              <ChevronDown size={16} className="mb-2 -rotate-90 text-ink-muted" />
              <div>
                <div className="font-mono text-[9px] uppercase text-ink-muted">After (proj.)</div>
                <div
                  className={`font-mono text-xl font-bold ${
                    reassessment.mitigated_below_threshold
                      ? "text-brand-normal"
                      : "text-brand-critical"
                  }`}
                >
                  {reassessment.after_response_gap.toFixed(2)}
                </div>
                <div className="font-mono text-[10px] text-ink-secondary">
                  {reassessment.after_risk_tier}
                </div>
              </div>
              <div className="ml-auto text-right">
                <div className="font-mono text-[9px] uppercase text-ink-muted">ΔR</div>
                <div
                  className={`font-mono text-lg font-bold ${
                    reassessment.projected_delta > 0
                      ? "text-brand-normal"
                      : "text-brand-critical"
                  }`}
                >
                  {reassessment.projected_delta > 0 ? "+" : ""}
                  {reassessment.projected_delta.toFixed(2)}
                </div>
                <div className="font-mono text-[9px] uppercase text-ink-muted">
                  below {reassessment.dispatch_threshold.toFixed(1)} →{" "}
                  {reassessment.mitigated_below_threshold ? "yes" : "no"}
                </div>
              </div>
            </div>
          )}

          {selected && (
            <div className="flex items-start gap-2">
              <GitBranch size={14} className="mt-0.5 shrink-0 text-brand-elevated" />
              <div className="min-w-0 flex-1">
                <p className="font-mono text-[11px] font-semibold uppercase tracking-wide text-ink-primary">
                  {selected.title}
                </p>
                <p className="mt-0.5 text-xs leading-relaxed text-ink-secondary">
                  {selected.message}
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1.5 font-mono text-[9px] uppercase text-ink-muted">
                  <span className="rounded border border-hairline px-1.5 py-0.5">
                    cost {selected.resource.cost}
                  </span>
                  <span className="rounded border border-hairline px-1.5 py-0.5">
                    eta {selected.resource.eta_min}m
                  </span>
                  <span className="rounded border border-brand-normal/30 bg-brand-normal/10 px-1.5 py-0.5 text-brand-normal">
                    status: {selected.status}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Why This Action */}
          <div className="mt-3 border-t border-hairline pt-3">
            <div className="mb-1 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-widest text-ink-secondary">
              <ShieldAlert size={12} /> Why this action
            </div>
            <p className="text-xs leading-relaxed text-ink-secondary">{why}</p>
          </div>
        </div>
      )}

      {/* ------------------------------------------------ decision trace */}
      {trace.length > 0 && (
        <div className="rounded-lg border border-hairline bg-panel/60">
          <button
            type="button"
            onClick={() => setOpenTrace((v) => !v)}
            className="flex w-full items-center gap-2 px-4 py-2.5 text-left"
          >
            <ShieldCheck size={13} className="text-ink-secondary" />
            <h3 className="font-mono text-[11px] font-semibold uppercase tracking-widest text-ink-secondary">
              Agent Decision Trace
            </h3>
            <span className="ml-auto font-mono text-[10px] text-ink-muted">
              {trace.length} entries
            </span>
            <ChevronDown
              size={14}
              className={`text-ink-muted transition-transform ${openTrace ? "rotate-180" : ""}`}
            />
          </button>

          {openTrace && (
            <ol className="divide-y divide-hairline/60 border-t border-hairline">
              {trace.map((d) => (
                <li key={d.id} className="flex gap-3 px-4 py-2.5">
                  <span className="mt-0.5 w-20 shrink-0 font-mono text-[10px] font-semibold uppercase text-brand-elevated">
                    {d.stage}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-xs font-semibold text-ink-primary">{d.action}</p>
                    <p className="mt-0.5 text-[11px] leading-relaxed text-ink-secondary">
                      {d.reason}
                    </p>
                    <div className="mt-1 flex items-center gap-2 font-mono text-[9px] text-ink-muted">
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
          )}
        </div>
      )}

      {/* ------------------------------------------------ audit tail */}
      {(metrics || incident?.escalation_reasons?.length) && (
        <div className="flex flex-wrap items-center gap-2 px-1 font-mono text-[9px] uppercase tracking-wide text-ink-muted">
          <CheckCircle2 size={11} className="text-brand-normal" />
          <span>audit ids on each trace entry · server-authoritative</span>
          {incident?.escalation_reasons?.length ? (
            <span className="text-brand-critical">· escalated: {incident.escalation_reasons.length}</span>
          ) : null}
        </div>
      )}
    </section>
  );
}
