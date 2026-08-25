"use client";

import { useMemo, useState } from "react";
import { Flame, RotateCcw, Zap } from "lucide-react";
import type { RiskBreakdown, RiskTier } from "@/lib/types";

/**
 * RadiantZoneSim
 * ===============
 * Interactive geofencing demo. Projects what would happen if a worker
 * moves from the baseline worksite into a high-radiant zone (e.g.
 * adjacent to asphalt, reflective steel, or a radiant heat source),
 * adding an industry-standard +4 °F radiant offset.
 *
 * The simulation reuses the production R = 0.40E + 0.35V + 0.25D
 * formula with its actual published component weights — clearly
 * labeled as a projection, never altering the audit artifact.
 *
 * Tier bands mirror scoring.py exactly:
 *   NORMAL   < 3.0
 *   ELEVATED 3.0 – 5.49
 *   HIGH     5.5 – 6.99
 *   CRITICAL ≥ 7.0
 */

const TIER_BANDS: [number, RiskTier][] = [
  [7.0, "CRITICAL"],
  [5.5, "HIGH"],
  [3.0, "ELEVATED"],
  [0, "NORMAL"],
];

function tierForScore(r: number): RiskTier {
  for (const [min, tier] of TIER_BANDS) {
    if (r >= min) return tier;
  }
  return "NORMAL";
}

const TIER_HEX: Record<RiskTier, string> = {
  NORMAL: "#22C55E",
  ELEVATED: "#F59E0B",
  HIGH: "#F97316",
  CRITICAL: "#DC2626",
};

/** +4 °F radiant maps to ≈ +1.5 E-subscore points on a 0–10 linear ramp. */
const RADIANT_DELTA_E = 1.5;

export default function RadiantZoneSim({
  breakdown,
  siteName,
  operation,
}: {
  breakdown: RiskBreakdown | null | undefined;
  siteName: string;
  operation: string;
}) {
  const [simulated, setSimulated] = useState(false);

  // Auto-reset when site/op context changes so stale sim doesn't linger.
  const contextKey = `${siteName}|${operation}`;
  const prevKey = useMemo(() => contextKey, []);
  if (contextKey !== prevKey && simulated) {
    setSimulated(false);
  }

  if (!breakdown) return null;

  const R = breakdown.response_gap;
  const currentTier = breakdown.risk_tier;

  const EComponent = breakdown.components.find(
    (c) => c.key === "heat_exposure"
  );
  const E_weight = EComponent?.weight ?? 0.40;
  const deltaR = Math.round(E_weight * RADIANT_DELTA_E * 1000) / 1000;
  const Rprime = Math.min(10, Math.round((R + deltaR) * 100) / 100);
  const simTier = tierForScore(Rprime);

  const simPeakF =
    (Number(breakdown.raw_inputs?.peak_temp_f) || 0) + 4;

  const label =
    breakdown.formula_substitution ?? `R = 0.40·E + 0.35·V + 0.25·D = ${R}`;

  return (
    <section className="rounded-lg border border-hairline bg-neutral-950/80 p-3 sm:p-4">
      {/* Header */}
      <header className="mb-3 flex flex-wrap items-center gap-2">
        <Flame size={14} className="text-red-500" />
        <h3 className="font-mono text-[11px] font-semibold uppercase tracking-widest text-ink-secondary">
          Geofence Simulation
        </h3>
        <span className="ml-auto rounded border border-hairline px-1.5 py-0.5 font-mono text-[9px] uppercase text-neutral-500">
          projection only · determinist formula reuse
        </span>
      </header>

      {/* Baseline vs projected */}
      <div className="mb-3 grid grid-cols-2 gap-2 font-mono text-[11px]">
        {/* BEFORE */}
        <div className="rounded border border-hairline bg-panel/50 px-3 py-2.5">
          <div className="mb-1 text-[9px] uppercase tracking-widest text-neutral-500">
            baseline (current site)
          </div>
          <div
            className="text-2xl font-bold tabular-nums"
            style={{ color: TIER_HEX[currentTier] }}
          >
            {R.toFixed(2)}
          </div>
          <div className="mt-0.5 text-[9px]" style={{ color: TIER_HEX[currentTier] }}>
            {currentTier}
          </div>
          <div className="mt-1 text-[9px] text-ink-muted">weight_E = {(E_weight * 100).toFixed(0)}%</div>
        </div>

        {/* AFTER — simulated */}
        <div
          className={`rounded px-3 py-2.5 transition-colors ${
            simulated
              ? "border-2 border-red-600/70 bg-red-950/50"
              : "border border-hairline bg-panel/50"
          }`}
        >
          <div className="mb-1 text-[9px] uppercase tracking-widest text-neutral-500">
            +4 °F radiant zone
          </div>
          <div
            className="text-2xl font-bold tabular-nums"
            style={{ color: simulated ? TIER_HEX[simTier] : "#737373" }}
          >
            {simulated ? Rprime.toFixed(2) : "—"}
          </div>
          <div className="mt-0.5 text-[9px]" style={{ color: simulated ? TIER_HEX[simTier] : "#737373" }}>
            {simulated ? simTier : "—"}
          </div>
          <div className="mt-1 text-[9px] text-ink-muted">
            {simulated ? `peak ≈ ${simPeakF.toFixed(1)}°F` : "tap to project"}
          </div>
        </div>
      </div>

      {/* Formula explanation */}
      {simulated && (
        <div className="mb-3 rounded bg-neutral-900/60 px-3 py-2 font-mono text-[10px] leading-relaxed text-ink-secondary">
          <span className="text-ink-muted">baseline:</span>{" "}
          {label}{" "}
          <span className="text-ink-muted">&nbsp;→&nbsp; radiant ΔE</span> +{RADIANT_DELTA_E}{" "}
          <span className="text-ink-muted">×</span> w_E {(E_weight * 100).toFixed(0)}%{" "}
          <span className="text-ink-muted">=</span> <span className="text-red-400">+{deltaR.toFixed(2)} R</span>
          {" "}
          <span className="text-ink-muted">→</span>{" "}
          <span
            className="font-bold"
            style={{ color: TIER_HEX[simTier] }}
          >
            R&apos; = {Rprime.toFixed(2)}
          </span>
          {" "}
          {R < 7 && Rprime >= 7 && (
            <span className="ml-1 inline-flex items-center gap-1 rounded bg-red-600 px-1.5 py-0.5 text-[9px] font-bold text-white animate-pulse_soft">
              <Zap size={9} /> DISPATCH ARMED
            </span>
          )}
          {R < 7 && Rprime < 7 && (
            <span className="ml-1 text-neutral-500">— no tier shift</span>
          )}
        </div>
      )}

      {/* Action row */}
      <div className="flex gap-2">
        {!simulated ? (
          <button
            onClick={() => setSimulated(true)}
            className="flex flex-1 min-h-[44px] items-center justify-center gap-2 rounded-lg border border-red-600/40 bg-red-950/60 px-3 py-2 font-mono text-[11px] font-medium text-red-300 transition hover:border-red-500 hover:bg-red-950/80"
          >
            <Flame size={13} />
            Simulate worker entering high radiant zone (+4 °F)
          </button>
        ) : (
          <button
            onClick={() => setSimulated(false)}
            className="flex flex-1 min-h-[44px] items-center justify-center gap-2 rounded-lg border border-hairline bg-panel/60 px-3 py-2 font-mono text-[11px] text-ink-secondary transition hover:border-neutral-500"
          >
            <RotateCcw size={13} />
            Reset to baseline
          </button>
        )}
      </div>

      {/* Footnote */}
      <p className="mt-2 font-mono text-[9px] leading-relaxed text-ink-muted">
        +4 °F offset matches the backend roadwork operation profile. The
        simulation reuses the published component weights (0.40E) from the
        deterministic artifact — it does not alter or replace the real scoring run.
      </p>
    </section>
  );
}
