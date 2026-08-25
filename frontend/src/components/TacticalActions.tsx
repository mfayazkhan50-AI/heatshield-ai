"use client";

import { CheckCircle2, PhoneCall, Radio, Send } from "lucide-react";
import type { DispatchRecord, EnterpriseOutput, TacticalAction } from "@/lib/types";

type DispatchMode = EnterpriseOutput["dispatch_mode"];

function maskPhone(to: string): string {
  if (to.length < 4) return to;
  return `${to.slice(0, -4).replace(/\d/g, "•")}${to.slice(-4)}`;
}

function displayTo(to: string): string {
  return to.includes("@") ? maskPhone(to) : maskPhone(to);
}

/**
 * TacticalActions — numbered field directives (01..06) plus the autonomous
 * telephony dispatch log when the Response Gap crossed 7.0.
 */
export default function TacticalActions({
  actions,
  dispatchRecords,
  dispatchMode,
}: {
  actions?: TacticalAction[];
  dispatchRecords?: DispatchRecord[];
  dispatchMode?: DispatchMode;
}) {
  if (!actions?.length && !dispatchRecords?.length) return null;

  return (
    <section className="space-y-3">
      {/* Numbered directives */}
      <div className="rounded-lg border border-hairline bg-panel/70">
        <header className="border-b border-hairline px-4 py-2.5">
          <h3 className="font-mono text-[11px] font-semibold uppercase tracking-widest text-ink-secondary">
            Tactical Directives
          </h3>
        </header>
        <ol className="divide-y divide-hairline/60">
          {(actions ?? []).map((a) => (
            <li key={a.id} className="flex gap-3 px-4 py-3">
              <span className="font-mono text-sm font-bold text-brand-elevated">
                {a.id}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-ink-primary">{a.title}</p>
                <p className="mt-0.5 text-xs leading-relaxed text-ink-secondary">
                  {a.detail}
                </p>
              </div>
              <span className="shrink-0 self-start rounded border border-hairline px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide text-ink-muted">
                {a.horizon}
              </span>
            </li>
          ))}
        </ol>
      </div>

      {/* Autonomous dispatch log */}
      {dispatchRecords && dispatchRecords.length > 0 && (
        <div className="rounded-lg border border-brand-critical/50 bg-brand-critical/[0.06]">
          <header className="flex items-center gap-2 border-b border-brand-critical/40 px-4 py-2.5">
            <Radio size={14} className="animate-pulse_soft text-brand-critical" />
            <h3 className="font-mono text-[11px] font-semibold uppercase tracking-widest text-brand-critical">
              Autonomous Dispatch Log — Response Gap ≥ 7.0
            </h3>
            <span className="ml-auto rounded bg-brand-critical/15 px-1.5 py-0.5 font-mono text-[9px] uppercase text-brand-critical">
              {dispatchMode === "live" ? "LIVE" : "DRY RUN"}
            </span>
          </header>

          <ul className="divide-y divide-brand-critical/25 font-mono text-xs">
            {dispatchRecords.map((r, i) => (
              <li key={`${r.to}-${i}`} className="flex items-start gap-3 px-4 py-2.5">
                {r.channel === "sms" ? (
                  <Send size={13} className="mt-0.5 shrink-0 text-brand-elevated" />
                ) : (
                  <PhoneCall size={13} className="mt-0.5 shrink-0 text-brand-high" />
                )}

                <div className="min-w-0 flex-1">
                  <p className="truncate text-ink-primary">
                    <span className="uppercase text-ink-secondary">{r.channel}</span>{" "}
                    → {displayTo(r.to)} · {r.site}
                  </p>
                  {(r.preview || r.error) && (
                    <p
                      className={`mt-0.5 truncate text-[10px] ${
                        r.error ? "text-brand-critical" : "text-ink-muted"
                      }`}
                    >
                      {r.error ?? r.preview}
                    </p>
                  )}
                </div>

                <span className="flex shrink-0 items-center gap-1 text-[10px]">
                  <CheckCircle2 size={12} className="text-brand-normal" />
                  {r.status.toUpperCase()}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
