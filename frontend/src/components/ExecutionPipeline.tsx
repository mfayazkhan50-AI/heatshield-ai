"use client";

import { Activity, CheckCircle2, Loader2, Radio } from "lucide-react";
import { NODE_LABELS, NODE_ORDER } from "@/lib/constants";
import type { ConnState, LogLine, NodePhase } from "@/lib/types";

const PHASE_BADGE: Record<NodePhase, string> = {
  idle: "border-hairline text-ink-muted",
  running:
    "border-thermal-warning bg-thermal-warning/10 text-thermal-warning animate-pulse_soft shadow-[0_0_14px_rgba(245,158,11,0.55)]",
  completed:
    "border-thermal-low bg-thermal-low/10 text-thermal-low shadow-[0_0_10px_rgba(59,130,246,0.35)]",
};

const PHASE_TEXT: Record<NodePhase, string> = {
  idle: "idle",
  running: "running",
  completed: "completed",
};

const CONN_BADGE: Record<ConnState, string> = {
  streaming: "bg-thermal-warning/15 text-thermal-warning",
  done: "bg-thermal-low/15 text-thermal-low",
  error: "bg-thermal-danger/15 text-thermal-danger",
  connecting: "bg-thermal-caution/15 text-thermal-caution",
  idle: "bg-hairline text-ink-muted",
};

export default function ExecutionPipeline({
  nodePhases,
  log,
  tokenTrace,
  connState,
  fromCache = false,
  apiBaseUrl,
}: {
  nodePhases: Record<string, NodePhase>;
  log: LogLine[];
  tokenTrace: string;
  connState: ConnState;
  fromCache?: boolean;
  apiBaseUrl: string;
}) {
  return (
    <div className="flex h-full flex-col gap-4">
      {/* Node pipeline tracker */}
      <div className="rounded-lg border border-hairline bg-panel/60 p-3 sm:p-4">
        <div className="mb-1 flex items-center gap-2 text-xs uppercase tracking-widest text-ink-secondary sm:text-sm">
          <Radio
            size={14}
            className={
              connState === "streaming" ? "animate-pulse_soft text-thermal-warning" : ""
            }
          />
          Agent Node Pipeline
          {fromCache && (
            <span className="ml-auto shrink-0 rounded bg-thermal-low/15 px-2 py-0.5 font-mono text-[10px] normal-case text-thermal-low">
              instant · cached
            </span>
          )}
        </div>
        <ol className="mt-3 space-y-2">
          {NODE_ORDER.map((node, idx) => {
            const phase = nodePhases[node] ?? "idle";
            return (
              <li key={node} className="flex min-w-0 items-center gap-2 sm:gap-3">
                <span
                  className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border font-mono text-[10px] transition-all ${PHASE_BADGE[phase]}`}
                >
                  {phase === "completed" ? (
                    <CheckCircle2 size={13} />
                  ) : phase === "running" ? (
                    <Loader2 size={13} className="animate-spin" />
                  ) : (
                    idx + 1
                  )}
                </span>
                <span
                  className={`min-w-0 flex-1 truncate font-mono text-xs sm:text-sm ${
                    phase === "idle" ? "text-ink-muted" : "text-ink-primary"
                  }`}
                >
                  {NODE_LABELS[node]}
                </span>
                <span
                  className={`shrink-0 rounded px-2 py-0.5 font-mono text-[9px] uppercase tracking-wide transition-all sm:text-[10px] ${
                    phase === "idle"
                      ? "text-ink-muted"
                      : phase === "running"
                      ? "bg-thermal-warning/15 text-thermal-warning"
                      : "bg-thermal-low/10 text-thermal-low"
                  }`}
                >
                  {PHASE_TEXT[phase]}
                </span>
              </li>
            );
          })}
        </ol>
      </div>

      {/* Live thinking / token trace */}
      <div className="min-h-[280px] flex-1 overflow-hidden rounded-lg border border-hairline bg-void/60">
        <div className="flex items-center justify-between gap-2 border-b border-hairline px-3 py-2 text-[10px] uppercase tracking-widest text-ink-secondary sm:px-4 sm:text-xs">
          <span className="flex items-center gap-2">
            <Activity size={13} />
            Live Reasoning Trace
          </span>
          <span className={`rounded px-2 py-0.5 font-mono text-[10px] ${CONN_BADGE[connState]}`}>
            {connState}
          </span>
        </div>
        <div className="h-56 overflow-y-auto p-3 font-mono text-[11px] leading-relaxed break-words sm:h-64 sm:p-4 sm:text-xs">
          {log.map((line) => {
            // Clean status-tag rendering instead of stacked alert text.
            let tag: string | null = null;
            let tagCls = "text-neutral-500";

            if (/— completed$/.test(line.text)) {
              tag = "[COMPLETED]";
              tagCls = "text-emerald-400/90";
            } else if (/— started$/.test(line.text)) {
              tag = "[RUNNING]";
              tagCls = "text-amber-400";
            } else if (/(deterministic|Tier 5|tier_5)/i.test(line.text)) {
              tag = "[FALLBACK]";
              tagCls = "text-amber-400/80";
            } else if (/(generated via|grounded|Tier [1-4])/i.test(line.text)) {
              tag = "[GROUNDED]";
              tagCls = "text-sky-400/80";
            } else if (line.kind === "error") {
              tag = "[ERROR]";
              // Subdued unless the whole connection actually failed.
              tagCls =
                connState === "error"
                  ? "text-red-400"
                  : "text-neutral-400";
            }

            return (
              <div key={line.id} className="flex gap-1.5">
                {tag && (
                  <span className={`shrink-0 font-bold ${tagCls}`}>{tag}</span>
                )}
                <span
                  className={
                    line.kind === "token"
                      ? "whitespace-pre-wrap text-thermal-caution/90"
                      : line.kind === "error" && connState === "error"
                        ? "text-red-300"
                        : "text-ink-secondary/90"
                  }
                >
                  {line.text}
                </span>
              </div>
            );
          })}
          {tokenTrace && !log.some((l) => l.kind === "token") && (
            <div className="mt-2 whitespace-pre-wrap text-thermal-caution/90">
              {tokenTrace}
            </div>
          )}
          {log.length === 0 && connState === "idle" && !fromCache && (
            <div className="text-ink-muted">Awaiting first run…</div>
          )}
        </div>
      </div>

      {connState === "error" && !fromCache && (
        <div className="flex items-center gap-2 rounded-lg border border-thermal-danger/40 bg-thermal-danger/10 px-3 py-2 text-xs text-thermal-danger">
          Stream connection lost. Check the backend is running at {apiBaseUrl}.
        </div>
      )}
    </div>
  );
}
