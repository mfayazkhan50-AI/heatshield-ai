"use client";

import { Sigma } from "lucide-react";
import type { RiskBreakdown, ScoreComponent } from "@/lib/types";

const COMPONENT_LABELS: Record<string, string> = {
  heat_exposure: "Heat Exposure (E)",
  vulnerability: "Vulnerability (V)",
  resource_deficit: "Resource Deficit (D)",
};

/**
 * DecisionRationale — "Why Flagged?" panel.
 *
 * Renders the deterministic artifact VERBATIM from the backend:
 * formula_expression, numeric substitution and per-component
 * weight × value = contribution. No frontend math anywhere.
 */
export default function DecisionRationale({
  breakdown,
}: {
  breakdown?: RiskBreakdown | null;
}) {
  if (!breakdown) return null;

  return (
    <section className="rounded-lg border border-hairline bg-panel/70 p-4">
      <header className="mb-3 flex items-center gap-2">
        <Sigma size={14} className="text-brand-elevated" />
        <h3 className="font-mono text-[11px] font-semibold uppercase tracking-widest text-ink-secondary">
          Why Flagged? — Deterministic Audit
        </h3>
        <span className="ml-auto rounded border border-brand-elevated/30 bg-brand-elevated/10 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide text-brand-elevated">
          engine {breakdown.engine}
        </span>
      </header>

      {/* Formula */}
      <div className="space-y-1.5 rounded-md bg-void/60 p-3 font-mono text-xs">
        <p className="text-ink-secondary">{breakdown.formula_expression}</p>
        <p
          data-testid="formula-substitution"
          className="font-bold leading-relaxed text-ink-primary"
        >
          {breakdown.formula_substitution} ={" "}
          <span
            className={
              breakdown.risk_tier === "CRITICAL"
                ? "text-brand-critical"
                : breakdown.risk_tier === "HIGH"
                  ? "text-brand-high"
                  : "text-brand-elevated"
            }
          >
            {breakdown.response_gap.toFixed(2)}
          </span>{" "}
          → {breakdown.risk_tier}
        </p>
      </div>

      {/* Component table */}
      <div className="mt-3 space-y-2.5">
        {breakdown.components.map((c) => (
          <ComponentRow key={c.key} component={c} />
        ))}
      </div>

      {/* Dispatch eligibility line */}
      <p className="mt-3 font-mono text-[10px] text-ink-muted">
        dispatch_threshold={breakdown.dispatch_threshold.toFixed(1)} ·
        dispatch_eligible=
        <span className={breakdown.dispatch_eligible ? "text-brand-critical" : "text-ink-muted"}>
          {String(breakdown.dispatch_eligible)}
        </span>
      </p>
    </section>
  );
}

function ComponentRow({ component }: { component: ScoreComponent }) {
  const label = COMPONENT_LABELS[component.key] ?? component.label;

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 font-mono text-[11px]">
        <span className="text-ink-primary">{label}</span>
        <span className="text-ink-muted">
          {component.value.toFixed(2)} ×{" "}
          <span className="text-brand-elevated">{component.weight}</span> ={" "}
          <span className="font-semibold text-ink-primary">
            +{component.contribution.toFixed(2)}
          </span>
        </span>
      </div>

      {/* weighted bar */}
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-panel-raised">
        <div
          className="h-full rounded-full bg-thermal-gradient transition-all duration-700"
          style={{ width: `${Math.min(100, component.contribution * 10)}%` }}
        />
      </div>

      {/* sub-inputs — the audit trail */}
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 font-mono text-[9px] text-ink-muted">
        {component.subs.map((s) => (
          <span key={s.key}>
            {s.label}=<span className="text-ink-secondary">{s.value}</span>
            <span className="opacity-60">×{s.sub_weight}</span>
          </span>
        ))}
        <span className="uppercase opacity-70">[{component.method}]</span>
      </div>
    </div>
  );
}
