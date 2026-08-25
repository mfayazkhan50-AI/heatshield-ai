"use client";

import { useMemo, useState } from "react";
import { ChevronDown, FileJson } from "lucide-react";
import type { AgentStreamParams } from "@/lib/types";

export default function DeveloperAuditPayload({
  params,
  rawResultJson,
}: {
  params: AgentStreamParams | null;
  rawResultJson: string | null;
}) {
  const prettyJson = useMemo(() => {
    if (!rawResultJson) return "No completed run yet.";
    try {
      return JSON.stringify(JSON.parse(rawResultJson), null, 2);
    } catch {
      return rawResultJson;
    }
  }, [rawResultJson]);

  return (
    <details className="group rounded-lg border border-hairline bg-panel/40">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-3 text-xs uppercase tracking-widest text-ink-muted transition-colors hover:text-ink-secondary sm:px-5 sm:text-sm [&::-webkit-details-marker]:hidden">
        <FileJson size={13} className="shrink-0" />
        Developer Audit Payload
        <span className="ml-auto hidden items-center gap-1 font-mono text-[10px] normal-case sm:flex">
          raw SSE result · debug only
          <ChevronDown
            size={14}
            className="transition-transform group-open:rotate-180"
          />
        </span>
      </summary>
      <div className="space-y-3 border-t border-hairline px-3 py-4 sm:px-5">
        {params && (
          <div className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2 lg:grid-cols-3">
            {(
              [
                ["thread_id", params.thread_id],
                ["location_name", params.location_name],
                ["latitude", String(params.latitude)],
                ["longitude", String(params.longitude)],
                ["byok_provider", params.byok_provider ?? "—"],
                ["byok_key", params.byok_key ? "•••• (set)" : "—"],
              ] as const
            ).map(([k, v]) => (
              <div key={k} className="flex justify-between gap-4">
                <span className="text-ink-muted">{k}</span>
                <span className="truncate font-mono text-ink-secondary">{v}</span>
              </div>
            ))}
          </div>
        )}
        <pre className="max-h-80 overflow-auto rounded border border-hairline bg-void/70 p-4 font-mono text-[11px] leading-relaxed text-ink-secondary">
          {prettyJson}
        </pre>
      </div>
    </details>
  );
}
