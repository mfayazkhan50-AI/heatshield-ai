"use client";

import { Download, FileText } from "lucide-react";
import type { EnterpriseOutput } from "@/lib/types";
import {
  downloadComplianceCsv,
  openPrintReport,
} from "@/lib/exportUtils";

/**
 * ComplianceExportBar
 * ===================
 * Enterprise-grade egress for the OSHA compliance log — placed at the
 * top of column 3 so it's the FIRST export affordance visible after a run.
 *
 * CSV  → Blob download (Excel / Google Sheets ready).
 * PDF  → styled self-contained print report → browser "Save as PDF".
 *
 * When no data is available yet, shows a muted hint so the export
 * capability is discoverable before the first run.
 */
export default function ComplianceExportBar({
  output,
}: {
  output: EnterpriseOutput | null;
}) {
  return (
    <div className="rounded-lg border border-hairline bg-panel/60 px-3 py-2.5 sm:px-4 sm:py-3">
      <div className="flex flex-wrap items-center gap-3">
        {/* Always-visible label so the feature is discoverable */}
        <span className="flex-1 font-mono text-[11px] font-semibold uppercase tracking-widest text-ink-secondary">
          {output
            ? "✓ compliance log ready — export below"
            : "export compliance log (OSHA audit trail)"}
        </span>

        <button
          disabled={!output}
          onClick={() => output && downloadComplianceCsv(output)}
          className="flex items-center gap-1.5 rounded border px-3 py-1.5 font-mono text-[10px] uppercase tracking-wide transition disabled:cursor-not-allowed disabled:opacity-30 border-hairline bg-panel text-ink-secondary hover:border-emerald-500/60 hover:text-emerald-400"
        >
          <Download size={13} />
          CSV
        </button>

        <button
          disabled={!output}
          onClick={() => output && openPrintReport(output)}
          className="flex items-center gap-1.5 rounded border px-3 py-1.5 font-mono text-[10px] uppercase tracking-wide transition disabled:cursor-not-allowed disabled:opacity-30 border-hairline bg-panel text-ink-secondary hover:border-amber-500/60 hover:text-amber-400"
        >
          <FileText size={13} />
          PDF report
        </button>
      </div>

      {!output && (
        <p className="mt-1.5 font-mono text-[9px] text-ink-muted">
          Run a site + operation to generate the OSHA audit log, then export it
          as CSV or a printable PDF report.
        </p>
      )}
    </div>
  );
}
