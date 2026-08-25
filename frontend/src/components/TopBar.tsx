"use client";

import type { RiskTier } from "@/lib/types";

/**
 * TopBar
 * ======
 * Global status propagation surface. Every accent in the header derives
 * from the live deterministic RiskTier:
 *
 *   - bottom border becomes a severity-scaled glowing accent line
 *   - shield mark fill/glow follows the tier hex
 *   - status pill carries a live ping dot (operational monitoring feel)
 */

interface TierAccent {
  /** Accent line classes applied to the <header> bottom border. */
  barCls: string;
  /** Text/border/bg for the status pill. */
  pillCls: string;
  hex: string;
}

const ACCENTS: Record<RiskTier, TierAccent> = {
  NORMAL: {
    barCls: "border-b border-emerald-500/70",
    pillCls: "border-emerald-500/40 bg-emerald-500/10 text-emerald-400",
    hex: "#22C55E",
  },
  ELEVATED: {
    barCls: "border-b-2 border-amber-500",
    pillCls: "border-amber-500/50 bg-amber-500/10 text-amber-400",
    hex: "#F59E0B",
  },
  HIGH: {
    barCls: "border-b-2 border-orange-500",
    pillCls: "border-orange-500/50 bg-orange-500/10 text-orange-400",
    hex: "#F97316",
  },
  CRITICAL: {
    barCls: "border-b-2 border-red-600 shadow-[0_4px_20px_rgba(220,38,38,0.3)]",
    pillCls: "border-red-600/60 bg-red-600/10 text-red-500",
    hex: "#DC2626",
  },
};

const IDLE_ACCENT: TierAccent = {
  barCls: "border-b border-hairline",
  pillCls: "hidden",
  hex: "#06B6D4",
};

export default function TopBar({
  threadId,
  tier,
}: {
  threadId: string;
  tier?: RiskTier | null;
}) {
  const accent = tier ? ACCENTS[tier] : IDLE_ACCENT;

  return (
    <header
      data-status={tier ?? "idle"}
      className={`sticky top-0 z-40 border-t border-transparent bg-void/85 backdrop-blur transition-all duration-500 ${accent.barCls}`}
    >
      <div className="mx-auto flex max-w-[1700px] flex-col items-start justify-between gap-3 px-4 py-4 sm:flex-row sm:items-center sm:px-6">
        {/* Brand mark — dynamic glow + fill */}
        <div className="flex items-center gap-3">
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded bg-panel-raised ring-1 ring-hairline"
            style={{
              filter: `drop-shadow(0 0 8px ${accent.hex}66)`,
              boxShadow: `0 0 18px ${accent.hex}2e`,
            }}
          >
            <svg width={18} height={18} viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"
                fill={`${accent.hex}30`}
                stroke={accent.hex}
                strokeWidth="1.5"
                style={{ transition: "fill .5s, stroke .5s" }}
              />
              <circle
                cx="12"
                cy="12"
                r="3"
                fill={accent.hex}
                style={{ transition: "fill .5s" }}
              />
            </svg>
          </div>
          <div className="min-w-0">
            <h1 className="font-display text-lg font-bold tracking-tight text-ink-primary sm:text-xl">
              HeatShield AI
            </h1>
            <p className="truncate text-[11px] text-ink-muted">
              Autonomous Heat Intelligence · Track 06 + 03
            </p>
          </div>
        </div>

        {/* Right cluster — live status pill + thread chip */}
        <div className="flex items-center gap-2">
          {tier && (
            <span
              className={`flex items-center gap-2 rounded-full border px-3 py-1 font-mono text-[10px] font-bold uppercase tracking-widest transition-colors duration-500 ${accent.pillCls}`}
            >
              {/* ping/pulse live indicator */}
              <span className="relative flex h-2 w-2">
                <span
                  className="absolute inline-flex h-full w-full animate-ping rounded-full opacity-60"
                  style={{ backgroundColor: accent.hex }}
                />
                <span
                  className="relative inline-flex h-2 w-2 rounded-full"
                  style={{ backgroundColor: accent.hex }}
                />
              </span>
              {tier}
            </span>
          )}

          <div className="flex min-w-0 max-w-full items-center gap-2 rounded-full border border-hairline px-3 py-1 font-mono text-[10px] text-ink-muted">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-thermal-low" />
            <span className="truncate">{threadId}</span>
          </div>
        </div>
      </div>
    </header>
  );
}
