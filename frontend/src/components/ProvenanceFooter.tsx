"use client";

import { Activity, Database, Hash, Timer } from "lucide-react";
import type {
  FieldSource,
  HeatmapResultPayload,
} from "@/lib/types";

const SOURCE_LABEL: Record<FieldSource, { label: string; cls: string }> = {
  live: { label: "LIVE FORTYGUARD", cls: "text-brand-normal" },
  cached: { label: "CACHE HIT", cls: "text-thermal-caution" },
  simulated: { label: "SIMULATED FIELD", cls: "text-brand-elevated" },
  deterministic_fallback: { label: "DETERMINISTIC FALLBACK", cls: "text-brand-high" },
};

/**
 * ProvenanceFooter — SOURCE | LATENCY | TILE COUNT | ACTIVITY ID.
 * The transparency strip that makes the demo audit-proof.
 */
export default function ProvenanceFooter({
  source,
  latencyMs,
  payload,
}: {
  source?: FieldSource | null;
  latencyMs?: number | null;
  payload?: HeatmapResultPayload | null;
}) {
  if (!source && !payload) return null;

  const src = (source ?? payload?.source ?? "simulated") as FieldSource;
  const meta = SOURCE_LABEL[src] ?? SOURCE_LABEL.simulated;
  const activityId = payload?.activity_id ?? "—";

  return (
    <footer
      data-testid="provenance-footer"
      className="flex flex-wrap items-center gap-x-5 gap-y-1.5 rounded-lg border border-hairline bg-panel/60 px-4 py-2.5 font-mono text-[10px] uppercase tracking-wider"
    >
      <span className="flex items-center gap-1.5">
        <Activity size={11} className="text-ink-muted" />
        <span className="text-ink-muted">source</span>
        <span className={`font-semibold ${meta.cls}`}>{meta.label}</span>
      </span>

      <span className="flex items-center gap-1.5">
        <Timer size={11} className="text-ink-muted" />
        <span className="text-ink-muted">latency</span>
        <span className="text-ink-primary">
          {(latencyMs ?? payload?.latency_ms ?? 0).toLocaleString()}ms
        </span>
      </span>

      <span className="flex items-center gap-1.5">
        <Database size={11} className="text-ink-muted" />
        <span className="text-ink-muted">tiles</span>
        <span className="text-ink-primary">
          {payload?.tile_count?.toLocaleString() ?? "—"}
          {payload?.critical_cells !== undefined &&
            ` · ${payload.critical_cells.toLocaleString()} crit`}
        </span>
      </span>

      <span className="ml-auto flex items-center gap-1.5">
        <Hash size={11} className="text-ink-muted" />
        <span className="text-ink-muted">activity</span>
        <span className="text-brand-elevated">{activityId.slice(0, 12)}</span>
      </span>
    </footer>
  );
}
