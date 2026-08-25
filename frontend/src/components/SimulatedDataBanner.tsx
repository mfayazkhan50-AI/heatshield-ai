"use client";

import { AlertTriangle } from "lucide-react";

/**
 * SimulatedDataBanner
 * ===================
 * THE single consolidated alert bar for field-provenance degradation.
 * Merges what used to be three competing warning surfaces into one sleek
 * amber strip: fallback reason, attempt count, and the assurance that the
 * deterministic scoring layer was unaffected.
 */
export default function SimulatedDataBanner({
  fallback,
  className = "",
}: {
  fallback?: {
    reason: string;
    message: string;
    attempts: number;
  } | null;
  className?: string;
}) {
  if (!fallback) return null;

  return (
    <div
      role="status"
      data-testid="simulated-data-banner"
      className={`relative overflow-hidden rounded-lg border border-amber-500/50 bg-amber-950/40 text-amber-200 ${className}`}
    >
      {/* animated diagonal sweep */}
      <div
        aria-hidden
        className="absolute inset-0 animate-banner_sweep bg-[linear-gradient(100deg,transparent_20%,rgba(245,158,11,0.12)_50%,transparent_80%)] bg-[length:200%_100%]"
      />
      <div className="relative flex items-start gap-3 px-4 py-2.5">
        <AlertTriangle size={16} className="mt-0.5 shrink-0 text-amber-400" />
        <div className="min-w-0 flex-1">
          <p className="font-mono text-xs font-semibold uppercase tracking-widest text-amber-300">
            {fallback.message}
          </p>
          <p className="mt-1 truncate font-mono text-[11px] text-amber-200/70">
            reason=<span className="text-amber-100">{fallback.reason}</span>
            {" · "}attempts={fallback.attempts}
            {" · "}
            <span className="text-emerald-400/80">
              deterministic scoring unaffected
            </span>
          </p>
        </div>
      </div>
    </div>
  );
}
