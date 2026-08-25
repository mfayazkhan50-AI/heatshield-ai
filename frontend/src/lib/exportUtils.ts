/**
 * Enterprise compliance-log exports — zero dependencies.
 *
 * CSV  → Blob download, opens natively in Excel/Sheets.
 * PDF  → self-contained styled report window + browser print
 *        ("Save as PDF"), avoiding a heavyweight jsPDF dependency.
 */

import type { EnterpriseOutput } from "./types";

function maskPhone(to: string): string {
  return to.length > 4 ? `***${to.slice(-4)}` : "***";
}

function csvCell(v: unknown): string {
  const s = String(v ?? "");
  // Quote anything containing commas/quotes/newlines.
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function buildComplianceCsv(output: EnterpriseOutput): string {
  const rows: string[][] = [];
  const b = output.risk_breakdown;

  rows.push(["section", "field", "value"]);
  rows.push([
    "run",
    "generated_at",
    new Date().toISOString(),
  ]);
  rows.push(["run", "location", output.location_name]);
  rows.push(["run", "latitude", String(output.latitude)]);
  rows.push(["run", "longitude", String(output.longitude)]);
  rows.push(["run", "operation_context", output.operation_context]);
  rows.push(["run", "observed_at", output.observed_at]);
  rows.push(["run", "activity_id", output.activity_id ?? "n/a"]);
  rows.push(["run", "data_source", output.source]);
  rows.push(["run", "resolved_by_tier", output.active_tier]);

  if (b) {
    rows.push(["scoring", "response_gap_R", String(b.response_gap)]);
    rows.push(["scoring", "risk_tier", b.risk_tier]);
    rows.push([
      "scoring",
      "dispatch_eligible",
      String(b.dispatch_eligible),
    ]);
    rows.push([
      "scoring",
      "dispatch_threshold",
      String(b.dispatch_threshold),
    ]);
    rows.push(["scoring", "formula", b.formula_expression]);
    rows.push(["scoring", "formula_substitution", b.formula_substitution]);

    for (const c of b.components) {
      rows.push([
        "component",
        `${c.key} (${c.label})`,
        `value=${c.value} weight=${c.weight} contribution=${c.contribution}`,
      ]);
    }
  }

  rows.push([
    "plan",
    "risk_level",
    output.compliance_plan?.risk_level ?? "",
  ]);
  rows.push([
    "plan",
    "heat_index_f",
    String(output.compliance_plan?.heat_index_f ?? ""),
  ]);
  rows.push([
    "plan",
    "work_rest_cycle",
    output.compliance_plan?.work_rest_cycle ?? "",
  ]);
  rows.push([
    "plan",
    "hydration_benchmark",
    output.compliance_plan?.hydration_benchmark ?? "",
  ]);

  for (const a of output.tactical_actions) {
    rows.push([
      "tactical_action",
      `${a.id} ${a.title} [${a.horizon}]`,
      a.detail,
    ]);
  }

  for (const d of output.dispatch_records) {
    rows.push([
      "dispatch",
      `${d.ts} ${d.channel.toUpperCase()} mode=${d.mode} status=${d.status}`,
      `to=${maskPhone(d.to)}${d.preview ? ` preview="${d.preview.replace(/\s+/g, " ")}"` : ""}`,
    ]);
  }

  return rows.map((r) => r.map(csvCell).join(",")).join("\r\n");
}

export function downloadComplianceCsv(output: EnterpriseOutput): void {
  const csv = buildComplianceCsv(output);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  const slug = output.location_name.toLowerCase().replace(/[^a-z0-9]+/g, "-");

  a.href = url;
  a.download = `heatshield-osha-log-${slug}-${Date.now()}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** Escape for safe HTML interpolation inside the report template. */
function esc(s: unknown): string {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

export function openPrintReport(output: EnterpriseOutput): void {
  const b = output.risk_breakdown;
  const tierHex =
    b?.risk_tier === "CRITICAL"
      ? "#DC2626"
      : b?.risk_tier === "HIGH"
        ? "#F97316"
        : b?.risk_tier === "ELEVATED"
          ? "#F59E0B"
          : "#22C55E";

  const componentRows = (b?.components ?? [])
    .map(
      (c) => `<tr>
        <td><b>${esc(c.label)}</b> <span class="dim">(${esc(c.key)})</span></td>
        <td>${c.value.toFixed(2)}</td>
        <td>${(c.weight * 100).toFixed(0)}%</td>
        <td>${c.contribution.toFixed(3)}</td>
      </tr>`
    )
    .join("");

  const actionRows = output.tactical_actions
    .map(
      (a) => `<li>
        <span class="aid">${esc(a.id)}</span> <b>${esc(a.title)}</b>
        <span class="chip">${esc(a.horizon)}</span>
        <div class="detail">${esc(a.detail)}</div>
      </li>`
    )
    .join("");

  const dispatchRows = output.dispatch_records.length
    ? output.dispatch_records
        .map(
          (d) => `<li>
            <b>${esc(d.channel.toUpperCase())}</b> → ${esc(maskPhone(d.to))}
            <span class="chip">${esc(d.mode)}</span> <span class="dim">${esc(d.status)}</span>
          </li>`
        )
        .join("")
    : `<li class="dim">No dispatch records (mode: ${esc(output.dispatch_mode)}).</li>`;

  const html = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<title>HeatShield AI — OSHA Compliance Log · ${esc(output.location_name)}</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Consolas, "Cascadia Mono", monospace; color: #111;
         padding: 28px 34px; font-size: 12px; }
  header { border-bottom: 3px solid ${tierHex}; padding-bottom: 10px; margin-bottom: 16px; }
  h1 { font-size: 19px; letter-spacing: 1px; }
  .sub { color: #555; margin-top: 4px; font-size: 11px; }
  .gap { display:inline-block; margin-top:8px; background:${tierHex}; color:#fff;
         padding:5px 12px; font-weight:bold; font-size:14px; letter-spacing:.5px; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 1.5px;
       margin: 18px 0 8px; border-bottom: 1px solid #ddd; padding-bottom: 4px; }
  table { width: 100%; border-collapse: collapse; }
  td, th { border: 1px solid #ccc; padding: 5px 8px; text-align: left; font-size: 11.5px; }
  th { background: #f2f2f2; }
  ul { list-style: none; }
  li { padding: 5px 0; border-bottom: 1px dashed #e3e3e3; }
  .aid { background:#111; color:#fff; padding:1px 7px; margin-right:5px; font-size:10.5px; }
  .chip { background:#eee; border:1px solid #ccc; padding:0 7px; font-size:10.5px; }
  .detail { color:#444; margin-top:3px; }
  .dim { color:#888; }
  .kv { display:flex; flex-wrap:wrap; gap:6px 22px; }
  footer { margin-top: 24px; padding-top: 8px; border-top: 1px solid #ddd;
           color: #777; font-size: 10px; }
  @media print { body { padding: 0; } }
</style>
</head>
<body>
  <header>
    <h1>HeatShield AI — OSHA Heat-Compliance Log</h1>
    <div class="sub">
      ${esc(output.location_name)} (${output.latitude.toFixed(4)}, ${output.longitude.toFixed(4)})
      &nbsp;·&nbsp; Operation: ${esc(output.operation_context)}
      &nbsp;·&nbsp; Observed: ${esc(output.observed_at)}
      &nbsp;·&nbsp; Source: ${esc(output.source)}
    </div>
    ${
      b
        ? `<span class="gap">Response Gap R = ${b.response_gap.toFixed(2)} / 10 · ${esc(b.risk_tier)}</span>`
        : ""
    }
  </header>

  <h2>Deterministic Scoring Audit</h2>
  ${
    b
      ? `<table>
      <tr><th>Component</th><th>Score</th><th>Weight</th><th>Contribution</th></tr>
      ${componentRows}
      <tr><td colspan="3"><b>R = 0.40E + 0.35V + 0.25D</b></td><td><b>${b.response_gap.toFixed(2)}</b></td></tr>
    </table>
    <p style="margin-top:6px" class="dim">${esc(b.formula_substitution)}</p>
    <p style="margin-top:4px">Dispatch gate: R ≥ ${b.dispatch_threshold} →
       ${b.dispatch_eligible ? "<b>ELIGIBLE (autonomous alerts fired)</b>" : "not triggered"}</p>`
      : `<p class="dim">No scoring artifact attached to this run.</p>`
  }

  <h2>Compliance Plan</h2>
  <div class="kv">
    <span><b>Risk level:</b> ${esc(output.compliance_plan?.risk_level)}</span>
    <span><b>Heat index:</b> ${output.compliance_plan?.heat_index_f}°F</span>
    <span><b>Work/rest cycle:</b> ${esc(output.compliance_plan?.work_rest_cycle)}</span>
    <span><b>Hydration:</b> ${esc(output.compliance_plan?.hydration_benchmark)}</span>
    <span><b>Escalation:</b> ${esc(output.compliance_plan?.escalation_protocol)}</span>
  </div>

  <h2>Tactical Directives (${output.tactical_actions.length})</h2>
  <ul>${actionRows}</ul>

  <h2>Autonomous Dispatch Log</h2>
  <ul>${dispatchRows}</ul>

  <footer>
    Generated by HeatShield AI · deterministic rule-engine artifact · resolved by tier:
    ${esc(output.active_tier)} · activity ${esc(output.activity_id ?? "n/a")}
  </footer>
</body>
</html>`;

  const w = window.open("", "_blank", "width=900,height=1000");
  if (!w) {
    alert("Popup blocked — allow popups to export the PDF report.");
    return;
  }
  w.document.write(html);
  w.document.close();
  w.focus();
  // Give the document a beat to paint before opening the print dialog.
  setTimeout(() => w.print(), 350);
}
