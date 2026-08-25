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
 * Enterprise-grade egress for the OSHA compliance log:
 *   - CSV: native Blob download (Excel/Sheets ready)
 *   - PDF: styled print-report window → browser "Save as PDF"
 *
 * Zero npm dependencies — the export layer ships with the app itself.
 */
export default function ComplianceExportBar({
  output,
}: {
  output: EnterpriseOutput | null;
}) {
  if (!output) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="mr-auto font-mono text-[9px] uppercase tracking-widest text-ink-muted">
        compliance log export · osha audit trail
      </span>
      <button
        onClick={() => downloadComplianceCsv(output)}
        className="flex min-h-[34px] items-center gap-1.5 rounded border border-hairline bg-panel/60 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wide text-ink-secondary transition hover:border-brand-normal/60 hover:text-brand-normal"
      >
        <Download size={12} />
        CSV
      </button>
      <button
        onClick={() => openPrintReport(output)}
        className="flex min-h-[34px] items-center gap-1.5 rounded border border-hairline bg-panel/60 px-3 py-1.5 font-mono text-[10px] uppercase tracking-wide text-ink-secondary transition hover:border-brand-elevated/60 hover:text-brand-elevated"
      >
        <FileText size={12} />
        PDF report
      </button>
    </div>
  );
}
