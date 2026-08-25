"use client";

import { useCallback, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import { MapPin, PlayCircle, RefreshCw, Zap } from "lucide-react";

import BYOKPrompt from "@/components/BYOKPrompt";
import ComplianceCards from "@/components/ComplianceCards";
import DecisionRationale from "@/components/DecisionRationale";
import DeveloperAuditPayload from "@/components/DeveloperAuditPayload";
import ExecutionPipeline from "@/components/ExecutionPipeline";
import OperationSelector from "@/components/OperationSelector";
import ProvenanceFooter from "@/components/ProvenanceFooter";
import SimulatedDataBanner from "@/components/SimulatedDataBanner";
import TacticalActions from "@/components/TacticalActions";
import TemporalHeatChart from "@/components/TemporalHeatChart";
import ThermalGauge from "@/components/ThermalGauge";
import TopBar from "@/components/TopBar";
import { useAgentStream } from "@/hooks/useAgentStream";
import { useHeatmapStream } from "@/hooks/useHeatmapStream";
import {
  API_BASE_URL,
  BRAND_STATUS,
  DEMO_SITES,
  brandTierFrom,
  threadIdForSite,
} from "@/lib/constants";
import type {
  AgentRunSummary,
  AgentStreamParams,
  CachedRun,
  LlmProvider,
  OperationContext,
  RiskTier,
} from "@/lib/types";

interface Site {
  name: string;
  lat: number;
  lon: number;
}

/** Canvas renderer loaded client-side only. */
const ThermalCanvasMap = dynamic(() => import("@/components/ThermalCanvasMap"), {
  ssr: false,
});

/* High-contrast selector hierarchy (Pillar 2):
   active → vivid amber border-2 + radial glow; inactive → muted gray. */
const SITE_ACTIVE_CLS =
  "border-2 border-amber-500/80 bg-amber-500/10 text-white shadow-[0_0_15px_rgba(245,158,11,0.2)]";
const SITE_ACTIVE_CRITICAL_CLS =
  "border-2 border-red-600/80 bg-red-600/10 text-white shadow-[0_0_15px_rgba(220,38,38,0.25)]";
const SITE_INACTIVE_CLS =
  "border border-transparent bg-neutral-900/60 text-neutral-400 hover:border-neutral-700 hover:text-neutral-200";

export default function Home() {
  const [site, setSite] = useState<Site>(DEMO_SITES[0]);
  const [operation, setOperation] = useState<OperationContext>("construction");
  const [locationCache, setLocationCache] = useState<Record<string, CachedRun>>({});
  const [hydratedKey, setHydratedKey] = useState<string | null>(null);
  const [activeRequest, setActiveRequest] = useState<AgentStreamParams | null>(null);
  const [byok, setByok] = useState<{
    provider?: LlmProvider;
    key?: string;
  }>({});

  /**
   * Capture the EXACT request parameters at trigger time. This object is
   * the single source of truth passed verbatim into the POST request
   * body, so a Miami selection can never leak Phoenix's coordinates or
   * thread id.
   */
  const buildRequest = useCallback(
    (
      target: Site = site,
      op: OperationContext = operation,
      creds: { provider?: LlmProvider; key?: string } = byok
    ): AgentStreamParams => ({
      thread_id: threadIdForSite(target.name),
      location_name: target.name,
      latitude: target.lat,
      longitude: target.lon,
      operation_context: op,
      byok_provider: creds.provider,
      byok_key: creds.key,
    }),
    [site, operation, byok]
  );

  // -------------------------------------------------------------------
  // NDJSON thermal-field stream (Pillar 2) — auto-runs per site/op.
  // -------------------------------------------------------------------

  const heatmapRequest = useMemo(
    () => ({
      location_name: site.name,
      latitude: site.lat,
      longitude: site.lon,
      operation_context: operation,
    }),
    [site.name, site.lat, site.lon, operation]
  );

  const heat = useHeatmapStream({ apiBaseUrl: API_BASE_URL, request: heatmapRequest });
  const heatBusy = heat.conn === "connecting" || heat.conn === "streaming";

  // -------------------------------------------------------------------
  // SSE agent run (Pillars 1 & 4 results)
  // -------------------------------------------------------------------

  const handleComplete = useCallback((summary: AgentRunSummary) => {
    const { response } = summary;
    if (!response.enterprise_output && !response.awaiting_byok) return;
    setLocationCache((prev) => ({
      ...prev,
      [summary.params.location_name]: {
        response,
        nodePhases: summary.nodePhases,
        log: summary.log,
        tokenTrace: summary.tokenTrace,
        rawResultJson: summary.rawResultJson,
        completedAt: new Date().toISOString(),
      },
    }));
  }, []);

  const stream = useAgentStream({
    apiBaseUrl: API_BASE_URL,
    params: activeRequest,
    onComplete: handleComplete,
  });

  /** Selecting a preset: hydrate from cache instantly, else fetch fresh. */
  function selectSite(next: Site) {
    if (next.name === site.name) return;

    setSite(next);

    // Clear the previous location's gauge/cards before anything renders.
    setHydratedKey(null);
    setActiveRequest(null);

    const cached = locationCache[next.name];
    if (cached) {
      // Instant switch — render cached trace + cards, no SSE re-run.
      setHydratedKey(next.name);
    } else {
      // Fresh fetch with the NEW location's exact parameters.
      setActiveRequest(buildRequest(next));
    }
  }

  /** Force a live re-run for the active site (also refreshes the cache). */
  function triggerRun() {
    setHydratedKey(null);
    setActiveRequest(buildRequest());
  }

  function handleOperationChange(op: OperationContext) {
    if (op === operation) return;
    setOperation(op);
    setHydratedKey(null);
    // Re-run both streams against the new operation profile.
    setActiveRequest(buildRequest(site, op));
  }

  function handleBYOKSubmit(provider: LlmProvider, key: string) {
    const creds = { provider, key };
    setByok(creds);
    setHydratedKey(null);
    setActiveRequest(buildRequest(site, operation, creds));
  }

  const cachedRun = hydratedKey ? locationCache[hydratedKey] : undefined;
  const fromCache = Boolean(cachedRun);

  const displayNodePhases = cachedRun?.nodePhases ?? stream.nodePhases;
  const displayLog = cachedRun?.log ?? stream.log;
  const displayTokenTrace = cachedRun?.tokenTrace ?? stream.tokenTrace;
  const displayConnState = cachedRun ? ("done" as const) : stream.connState;
  const displayResponse = cachedRun?.response ?? stream.response;

  const result = displayResponse?.enterprise_output ?? undefined;
  const plan = result?.compliance_plan;
  const breakdown =
    displayResponse?.risk_breakdown ?? result?.risk_breakdown ?? null;
  const tacticalActions =
    displayResponse?.tactical_actions ?? result?.tactical_actions;
  const dispatchRecords =
    displayResponse?.dispatch_records ?? result?.dispatch_records;
  const dispatchMode =
    displayResponse?.dispatch_mode ?? result?.dispatch_mode;
  const awaitingBYOK = displayResponse?.awaiting_byok === true;

  // Brand status propagation — every accent follows the deterministic tier.
  const brandTier: RiskTier | null = brandTierFrom(breakdown, result?.risk_level);
  const brand = brandTier ? BRAND_STATUS[brandTier] : null;

  const auditParams = useMemo(
    () => (cachedRun || activeRequest ? buildRequest() : null),
    [cachedRun, activeRequest, buildRequest]
  );

  const auditRawJson = cachedRun?.rawResultJson ?? stream.rawResultJson;

  const threadId = threadIdForSite(site.name);

  const sourceLabel = useMemo(() => {
    if (!result) return null;
    if (result.source === "live")
      return { text: "Live FortyGuard feed", tone: "text-thermal-low" };
    if (result.source === "cached")
      return { text: "Cached historical frame", tone: "text-thermal-caution" };
    if (result.source === "simulated")
      return { text: "Simulated field", tone: "text-brand-elevated" };
    return { text: "Deterministic fallback", tone: "text-thermal-warning" };
  }, [result]);

  const busy = stream.connState === "connecting" || stream.connState === "streaming";

  return (
    <main className="min-h-screen overflow-x-hidden">
      {/* -------------------------------------------------------------- */}
      {/* TopBar — global risk status propagation (Pillar 3)              */}
      {/* -------------------------------------------------------------- */}
      <TopBar threadId={threadId} tier={brandTier} />

      {/* -------------------------------------------------------------- */}
      {/* Dashboard grid                                                  */}
      {/* -------------------------------------------------------------- */}
      <div className="mx-auto max-w-[1700px] px-4 py-6 sm:px-6 sm:py-8">
        <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-12 lg:gap-6">
          {/* -------------------------------------------------------- */}
          {/* COLUMN 1 — Input / Status                                 */}
          {/* -------------------------------------------------------- */}
          <aside className="col-span-1 flex flex-col gap-4 sm:gap-5 lg:col-span-3 lg:self-start lg:sticky lg:top-6">
            <div className={`rounded-lg border bg-panel/60 p-3 transition-colors duration-500 sm:p-5 ${brand ? brand.borderCls : "border-hairline"}`}>
              <div className="mb-3 flex items-center gap-2 text-xs uppercase tracking-widest text-ink-secondary sm:text-sm">
                <MapPin size={13} />
                Worksite Parameters
              </div>
              <div className="space-y-2">
                {DEMO_SITES.map((s) => {
                  const isActive = site.name === s.name;
                  const activeCls =
                    isActive && brandTier === "CRITICAL"
                      ? SITE_ACTIVE_CRITICAL_CLS
                      : isActive
                        ? SITE_ACTIVE_CLS
                        : SITE_INACTIVE_CLS;

                  return (
                    <button
                      key={s.name}
                      onClick={() => selectSite(s)}
                      disabled={busy}
                      aria-pressed={isActive}
                      className={`relative flex min-h-[44px] w-full flex-wrap items-center rounded border px-3 py-2 text-left text-sm transition-all duration-150 ${activeCls} ${
                        busy ? "cursor-not-allowed opacity-70" : ""
                      }`}
                    >
                      {isActive && (
                        <span className="relative mr-2 flex h-2 w-2 shrink-0">
                          <span
                            className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${
                              brandTier === "CRITICAL" ? "bg-red-500" : "bg-amber-400"
                            }`}
                          />
                          <span
                            className={`relative inline-flex h-2 w-2 rounded-full ${
                              brandTier === "CRITICAL"
                                ? "bg-red-500 shadow-[0_0_8px_rgba(220,38,38,0.9)]"
                                : "bg-amber-400 shadow-[0_0_8px_rgba(245,158,11,0.9)]"
                            }`}
                          />
                        </span>
                      )}
                      <span>{s.name}</span>
                      <span
                        className={`ml-2 font-mono text-[10px] ${
                          isActive ? "text-white/50" : "text-neutral-600"
                        }`}
                      >
                        {s.lat.toFixed(2)}, {s.lon.toFixed(2)}
                      </span>
                      {locationCache[s.name] && (
                        <Zap size={11} className="ml-auto inline text-thermal-low" />
                      )}
                    </button>
                  );
                })}
              </div>

              <div className="mt-4">
                <OperationSelector value={operation} onChange={handleOperationChange} />
              </div>

              <button
                onClick={triggerRun}
                disabled={busy}
                className="mt-4 flex min-h-[44px] w-full cursor-pointer items-center justify-center gap-2 rounded-lg border border-amber-400/30 bg-amber-600 px-4 py-3 text-sm font-semibold text-white shadow-md shadow-amber-950/50 transition-all hover:bg-amber-500 active:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <PlayCircle size={16} />
                {busy ? "Running…" : "Run Heat Intelligence Agent"}
              </button>
            </div>

            <ThermalGauge
              riskLevel={result?.risk_level}
              heatIndex={result?.heat_index_f}
              responseGap={breakdown?.response_gap}
            />

            <TemporalHeatChart
              anchorTempF={
                Number(
                  heat.payload?.peak_temp_f ??
                    breakdown?.raw_inputs?.heat_index_f ??
                    result?.heat_index_f ??
                    NaN
                ) || null
              }
              criticalHours={heat.payload?.consecutive_hours_above_40c ?? null}
              observedAt={heat.payload?.observed_at ?? result?.observed_at ?? null}
            />

            {fromCache && (
              <div className="flex items-center gap-2 rounded-lg border border-thermal-low/30 bg-thermal-low/5 px-3 py-2 text-xs text-thermal-low">
                <Zap size={13} className="shrink-0" />
                Rendered instantly from location cache ({cachedRun?.completedAt
                  ? new Date(cachedRun.completedAt).toLocaleTimeString()
                  : ""}
                ).
              </div>
            )}

            {result && (
              <div className="rounded-lg border border-hairline bg-panel/60 p-3 sm:p-5">
                <div className="mb-3 text-xs uppercase tracking-widest text-ink-secondary sm:text-sm">
                  Data Provenance
                </div>
                <div className="space-y-2 text-xs">
                  <div className="flex justify-between gap-2">
                    <span className="shrink-0 text-ink-muted">Source</span>
                    <span className={`truncate ${sourceLabel?.tone}`}>
                      {sourceLabel?.text}
                    </span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="shrink-0 text-ink-muted">Resolved tier</span>
                    <span className="truncate text-right text-ink-primary">
                      {result.active_tier}
                    </span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="shrink-0 text-ink-muted">Activity</span>
                    <span className="font-mono text-ink-primary">
                      {(displayResponse?.activity_id ?? result.activity_id)?.slice(0, 12) ?? "—"}
                    </span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span className="shrink-0 text-ink-muted">Observed</span>
                    <span className="font-mono text-ink-primary">{result.observed_at}</span>
                  </div>
                </div>
                {result.tier_trace && result.tier_trace.length > 0 && (
                  <div className="mt-3 border-t border-hairline pt-3">
                    <div className="mb-1 text-[10px] uppercase tracking-widest text-ink-muted">
                      Cascade trace
                    </div>
                    <ul className="space-y-1 font-mono text-[10px] text-ink-secondary">
                      {result.tier_trace.map((t, i) => (
                        <li key={i}>{t}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            <BYOKPrompt visible={awaitingBYOK} onSubmit={handleBYOKSubmit} />
          </aside>

          {/* -------------------------------------------------------- */}
          {/* COLUMN 2 — Live Thermal Field (NDJSON stream)             */}
          {/* -------------------------------------------------------- */}
          <section className="col-span-1 flex min-w-0 flex-col gap-4 lg:col-span-4">
            <SimulatedDataBanner fallback={heat.fallback} />

            <ThermalCanvasMap
              cells={heat.cells}
              payload={heat.payload}
              refetching={heatBusy}
              fitKey={`${site.name}|${operation}|${heat.payload?.activity_id ?? ""}`}
            />

            <ProvenanceFooter
              source={heat.payload?.source}
              latencyMs={heat.latencyMs}
              payload={heat.payload}
            />

            {/* Poll progress / errors / manual refresh */}
            {heatBusy && heat.progress && (
              <div className="rounded-lg border border-hairline bg-panel/60 px-3 py-2 font-mono text-[10px] text-ink-secondary">
                <span className="mr-2 inline-block h-1.5 w-1.5 animate-pulse_soft rounded-full bg-brand-elevated align-middle" />
                polling FortyGuard — attempt {heat.progress.attempt}/
                {heat.progress.max}
                {" · "}
                {(heat.progress.elapsed_ms / 1000).toFixed(1)}s elapsed
              </div>
            )}
            {heat.error && (
              <div className="rounded-lg border border-brand-critical/40 bg-brand-critical/10 px-3 py-2 font-mono text-[10px] text-brand-critical">
                {heat.error}
              </div>
            )}
            <button
              onClick={() => void heat.refetch()}
              disabled={heatBusy}
              className="flex min-h-[36px] items-center justify-center gap-2 rounded-lg border border-hairline px-3 py-2 font-mono text-[11px] uppercase tracking-wide text-ink-secondary transition hover:border-brand-elevated/50 hover:text-brand-elevated disabled:cursor-not-allowed disabled:opacity-50"
            >
              <RefreshCw size={13} className={heatBusy ? "animate-spin" : ""} />
              {heat.cacheHit ? "Cache hit — force refresh" : "Refresh thermal field"}
            </button>

            {breakdown && <DecisionRationale breakdown={breakdown} />}
          </section>

          {/* -------------------------------------------------------- */}
          {/* COLUMN 3 — Pipeline + Action Plan                         */}
          {/* -------------------------------------------------------- */}
          <section className="col-span-1 flex min-w-0 flex-col gap-4 lg:col-span-5">
            <ExecutionPipeline
              nodePhases={displayNodePhases}
              log={displayLog}
              tokenTrace={displayTokenTrace}
              connState={displayConnState}
              fromCache={fromCache}
              apiBaseUrl={API_BASE_URL}
            />
            <ComplianceCards plan={plan} />
            <TacticalActions
              actions={tacticalActions}
              dispatchRecords={dispatchRecords}
              dispatchMode={dispatchMode}
            />
          </section>
        </div>

        {/* Raw debug output kept out of the core interface */}
        <div className="mt-4 lg:mt-6">
          <DeveloperAuditPayload params={auditParams} rawResultJson={auditRawJson} />
        </div>
      </div>
    </main>
  );
}
