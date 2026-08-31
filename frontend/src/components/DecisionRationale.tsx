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
          Why Flagged?
        </h3>
        <span className="rounded border border-brand-elevated/40 bg-brand-elevated/10 px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase tracking-wider text-brand-elevated">
          DETERMINISTIC AUDIT
        </span>
        <span className="ml-auto font-mono text-[9px] uppercase tracking-wide text-ink-muted">
          engine {breakdown.engine.split("/")[0]}
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

      {/* Weight legend — E / V / D mapping from the backend components */}
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-0.5 font-mono text-[10px] text-ink-secondary">
        <span className="text-ink-muted">R =</span>
        {breakdown.components.map((c, i) => (
          <span key={c.key}>
            <span className="text-brand-elevated">{c.weight.toFixed(2)}</span>×
            <span className={c.key === "heat_exposure" ? "text-thermal-warning" : c.key === "vulnerability" ? "text-brand-elevated" : "text-ink-primary"}>
              {c.key === "heat_exposure" ? "E" : c.key === "vulnerability" ? "V" : "D"}
            </span>
            {i < breakdown.components.length - 1 ? <span className="ml-0.5">+</span> : null}
          </span>
        ))}
      </div>

      {/* Component table */}
      <div className="mt-3 space-y-2.5">
        {breakdown.components.map((c) => (
          <ComponentRow key={c.key} component={c} />
        ))}
      </div>

      <p className="mt-3 border-t border-hairline pt-2 font-mono text-[9px] uppercase tracking-wide text-ink-muted">
        rule engine computes the score · verbatim deterministic audit · no LLM math
      </p>

      {/* Dispatch eligibility line */}
      <p className="mt-2 font-mono text-[10px] text-ink-muted">
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
  const letter = component.key === "heat_exposure" ? "E" : component.key === "vulnerability" ? "V" : "D";

  return (
    <div>
      <div className="flex items-baseline justify-between gap-2 font-mono text-[11px]">
        <span className="text-ink-primary">
          <span className="mr-1 inline-block w-3 text-brand-elevated">{letter}</span>
          {label}
        </span>
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
