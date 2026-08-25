"use client";

import { Droplets, HardHat, ShieldAlert, Thermometer, Wind } from "lucide-react";
import type { CompliancePlan } from "@/lib/types";

export default function ComplianceCards({ plan }: { plan?: CompliancePlan }) {
  if (!plan) {
    return (
      <div className="flex h-full min-h-[280px] items-center justify-center rounded-lg border border-dashed border-hairline bg-panel/30 p-6 text-center">
        <p className="max-w-xs text-sm text-ink-muted">
          Run the Heat Intelligence Agent to generate the OSHA compliance action
          plan for the selected worksite.
        </p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <div className="rounded-lg border border-hairline bg-panel/60 p-3 sm:p-5">
        <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-widest text-ink-secondary sm:text-sm">
          <Thermometer size={13} />
          Work / Rest Cycle
        </div>
        <p className="text-sm text-ink-primary">{plan.work_rest_cycle}</p>
      </div>

      <div className="rounded-lg border border-hairline bg-panel/60 p-3 sm:p-5">
        <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-widest text-ink-secondary sm:text-sm">
          <Droplets size={13} />
          Hydration Benchmark
        </div>
        <p className="text-sm text-ink-primary">{plan.hydration_benchmark}</p>
      </div>

      <div className="rounded-lg border border-hairline bg-panel/60 p-3 sm:p-5">
        <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-widest text-ink-secondary sm:text-sm">
          <Wind size={13} />
          Monitoring Indicators
        </div>
        <ul className="space-y-1 text-sm text-ink-primary">
          {plan.monitoring_indicators?.map((m, i) => (
            <li key={i}>· {m}</li>
          ))}
        </ul>
      </div>

      <div className="rounded-lg border border-hairline bg-panel/60 p-3 sm:p-5">
        <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-widest text-ink-secondary sm:text-sm">
          <HardHat size={13} />
          Mandatory PPE
        </div>
        <ul className="space-y-1 text-sm text-ink-primary">
          {plan.mandatory_ppe?.length ? (
            plan.mandatory_ppe.map((p, i) => <li key={i}>· {p}</li>)
          ) : (
            <li className="text-ink-muted">None required at this level</li>
          )}
        </ul>
      </div>

      <div className="rounded-lg border border-thermal-danger/30 bg-thermal-danger/5 p-3 sm:p-5 md:col-span-2">
        <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-widest text-thermal-danger">
          <ShieldAlert size={13} />
          Escalation Protocol
        </div>
        <p className="text-sm text-ink-primary">{plan.escalation_protocol}</p>
      </div>
    </div>
  );
}
