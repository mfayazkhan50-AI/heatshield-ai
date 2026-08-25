"use client";

import { riskGaugePosition, RISK_COLOR } from "@/lib/constants";

export default function ThermalGauge({
  riskLevel,
  heatIndex,
  responseGap,
}: {
  riskLevel?: string;
  heatIndex?: number;
  /** Deterministic Response Gap R (0-10) from engine/scoring.py */
  responseGap?: number;
}) {
  const pct = riskGaugePosition(riskLevel);

  return (
    <div className="w-full rounded-xl border border-hairline bg-panel/60 p-3 shadow-lg shadow-black/30 sm:p-5">
      <div className="mb-4 flex items-baseline justify-between gap-2">
        <span className="text-xs uppercase tracking-widest text-ink-secondary sm:text-sm">
          Heat Index Gauge
        </span>
        <span className="font-tabular font-mono text-xl font-medium text-ink-primary sm:text-2xl">
          {heatIndex !== undefined ? (
            <>
              {heatIndex}
              <span className="ml-0.5 text-xs text-ink-secondary sm:text-sm">°F</span>
            </>
          ) : (
            "—"
          )}
        </span>
      </div>

      <div className="relative h-3 w-full overflow-hidden rounded-full bg-thermal-gradient ring-1 ring-inset ring-white/10">
        {riskLevel && (
          <div
            className="absolute top-1/2 h-5 w-[3px] -translate-y-1/2 rounded bg-white shadow-[0_0_10px_rgba(255,255,255,0.95),0_0_18px_rgba(255,255,255,0.45)] transition-all duration-700 ease-out"
            style={{ left: `${pct}%` }}
          />
        )}
      </div>
      <div className="mt-2 flex w-full justify-between font-mono text-[9px] uppercase tracking-wide text-ink-muted sm:text-[10px]">
        <span>Low</span>
        <span>Caution</span>
        <span>Warning</span>
        <span>Danger</span>
        <span>Extreme</span>
      </div>
      {riskLevel && (
        <div className="mt-4 flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border border-hairline bg-panel-raised px-3 py-2.5">
          <span
            className={`block h-1.5 w-1.5 shrink-0 rounded-full bg-current ${
              RISK_COLOR[riskLevel] ?? "text-ink-muted"
            }`}
          />
          <span className="text-[10px] uppercase tracking-wider text-ink-muted sm:text-[11px]">
            Current classification
          </span>
          <span
            className={`ml-auto font-mono text-xs font-semibold ${
              RISK_COLOR[riskLevel] ?? "text-ink-primary"
            }`}
          >
            {riskLevel}
          </span>
        </div>
      )}
      {responseGap !== undefined && (
        <div className="mt-2 flex items-center justify-between rounded-lg border border-brand-elevated/30 bg-brand-elevated/[0.07] px-3 py-2.5">
          <span className="font-mono text-[10px] uppercase tracking-widest text-ink-muted">
            Response Gap R
          </span>
          <span className="font-mono text-sm font-bold text-brand-elevated">
            {responseGap.toFixed(2)}
            <span className="ml-1 text-[10px] font-normal text-ink-muted">/ 10</span>
          </span>
        </div>
      )}
    </div>
  );
}
