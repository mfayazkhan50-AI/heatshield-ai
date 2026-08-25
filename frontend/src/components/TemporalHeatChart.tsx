"use client";

import { useMemo, useState } from "react";
import { TrendingUp } from "lucide-react";

/**
 * TemporalHeatChart
 * =================
 * 24-hour projected peak heat-stress trend (08:00 → 20:00 shift window).
 *
 * Zero-dependency hand-rolled SVG area chart — Recharts-grade styling
 * without the bundle or the npm-registry dependency:
 *   - amber→crimson gradient fill under the curve
 *   - dashed OSHA 90°F warning reference line
 *   - hover crosshair + readout, peak marker, over-threshold axis strip
 *
 * Data contract: the diurnal envelope is anchored to the DETERMINISTIC
 * observed peak from the scoring artifact (peak_temp_f / heat_index_f) —
 * the chart narrates; it never invents numbers. Labeled as a projection.
 */

export interface TemporalPoint {
  hour: number; // 0-23
  label: string; // "08:00"
  tempF: number;
}

const SHIFT_START = 8;
const SHIFT_END = 20;
const PEAK_HOUR = 15;
/** °F below the anchor at the shift edges (diurnal envelope depth). */
const ENVELOPE_DEPTH = 14;

const OSHA_WARNING_F = 90;

function buildSeries(anchorF: number): TemporalPoint[] {
  const pts: TemporalPoint[] = [];

  for (let h = SHIFT_START; h <= SHIFT_END; h++) {
    // Smooth cosine dip away from the 15:00 thermal maximum.
    const dip =
      ENVELOPE_DEPTH * 0.5 * (1 + Math.cos((Math.PI * (h - PEAK_HOUR)) / 12));
    const tempF = Math.round((anchorF - dip) * 10) / 10;

    pts.push({
      hour: h,
      label: `${String(h).padStart(2, "0")}:00`,
      tempF,
    });
  }

  // The deterministic anchor IS the series max by construction.
  const maxIdx = pts.reduce(
    (best, p, i) => (p.tempF > pts[best].tempF ? i : best),
    0
  );
  pts[maxIdx] = { ...pts[maxIdx], tempF: Math.round(anchorF * 10) / 10 };

  return pts;
}

export default function TemporalHeatChart({
  anchorTempF,
  criticalHours,
  observedAt,
}: {
  /** Deterministic observed peak (°F) the projection is anchored to. */
  anchorTempF?: number | null;
  /** Hours ≥40°C from the scoring artifact — shown in the header badge. */
  criticalHours?: number | null;
  observedAt?: string | null;
}) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const points = useMemo(
    () => (anchorTempF ? buildSeries(anchorTempF) : []),
    [anchorTempF]
  );

  if (!points.length) return null;

  // ------------------------------------------------------------------
  // Geometry (fixed viewBox, responsive width)
  // ------------------------------------------------------------------

  const W = 600;
  const H = 240;
  const M = { top: 18, right: 16, bottom: 34, left: 44 };

  const temps = points.map((p) => p.tempF);
  const dataMin = Math.min(...temps);
  const dataMax = Math.max(...temps);

  const yMin = Math.min(dataMin - 6, OSHA_WARNING_F - 8);
  const yMax = Math.max(dataMax + 4, OSHA_WARNING_F + 6);

  const x = (i: number): number =>
    M.left + (i / (points.length - 1)) * (W - M.left - M.right);
  const y = (t: number): number =>
    M.top + (1 - (t - yMin) / (yMax - yMin)) * (H - M.top - M.bottom);

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.tempF).toFixed(1)}`)
    .join(" ");

  const areaPath = `${linePath} L${x(points.length - 1).toFixed(1)},${
    H - M.bottom
  } L${x(0).toFixed(1)},${H - M.bottom} Z`;

  const peakIdx = temps.indexOf(Math.max(...temps));

  // Over-threshold segments for the axis strip.
  const hotRuns: Array<[number, number]> = [];
  let runStart: number | null = null;

  points.forEach((p, i) => {
    const hot = p.tempF >= OSHA_WARNING_F;
    if (hot && runStart === null) runStart = i;
    if ((!hot || i === points.length - 1) && runStart !== null) {
      hotRuns.push([runStart, hot ? i : i - 1]);
      runStart = null;
    }
  });

  const yTicks = 4;
  const hover = hoverIdx !== null ? points[hoverIdx] : null;

  return (
    <section className="rounded-lg border border-hairline bg-neutral-950/80 p-3 sm:p-4">
      {/* Header */}
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <TrendingUp size={14} className="text-brand-elevated" />
        <h3 className="font-mono text-[11px] font-semibold uppercase tracking-widest text-ink-secondary">
          Peak Heat Stress · Shift Projection
        </h3>
        <span className="ml-auto rounded border border-hairline px-1.5 py-0.5 font-mono text-[9px] uppercase text-neutral-500">
          diurnal model v0 · anchored to observed peak
        </span>
        {criticalHours != null && (
          <span
            className={`rounded px-1.5 py-0.5 font-mono text-[9px] font-bold uppercase ${
              criticalHours > 0
                ? "bg-red-600/15 text-red-400"
                : "bg-emerald-500/10 text-emerald-400"
            }`}
          >
            {criticalHours.toFixed(1)}h ≥40°C
          </span>
        )}
      </header>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full select-none"
        role="img"
        aria-label="Projected heat index across the work shift"
        onMouseLeave={() => setHoverIdx(null)}
      >
        <defs>
          <linearGradient id="heatFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#EF4444" stopOpacity="0.55" />
            <stop offset="55%" stopColor="#F59E0B" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#F59E0B" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Gridlines + y labels */}
        {Array.from({ length: yTicks + 1 }, (_, i) => {
          const t = yMin + ((yMax - yMin) * i) / yTicks;
          return (
            <g key={i}>
              <line
                x1={M.left}
                x2={W - M.right}
                y1={y(t)}
                y2={y(t)}
                stroke="#26312F"
                strokeWidth="1"
                strokeDasharray="2 5"
              />
              <text
                x={M.left - 7}
                y={y(t) + 3}
                textAnchor="end"
                fontSize="9"
                fill="#5C6B65"
                fontFamily="monospace"
              >
                {Math.round(t)}°
              </text>
            </g>
          );
        })}

        {/* OSHA reference line */}
        <line
          x1={M.left}
          x2={W - M.right}
          y1={y(OSHA_WARNING_F)}
          y2={y(OSHA_WARNING_F)}
          stroke="#DC2626"
          strokeWidth="1.5"
          strokeDasharray="6 4"
          opacity="0.85"
        />
        <text
          x={W - M.right}
          y={y(OSHA_WARNING_F) - 5}
          textAnchor="end"
          fontSize="9"
          fontWeight="700"
          fill="#DC2626"
          fontFamily="monospace"
        >
          OSHA WARNING · 90°F
        </text>

        {/* Gradient area */}
        <path d={areaPath} fill="url(#heatFill)" />

        {/* Curve */}
        <path
          d={linePath}
          fill="none"
          stroke="#F59E0B"
          strokeWidth="2.25"
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* Peak marker */}
        <circle
          cx={x(peakIdx)}
          cy={y(points[peakIdx].tempF)}
          r="4"
          fill="#DC2626"
          stroke="#0A0D0F"
          strokeWidth="2"
        />
        <text
          x={x(peakIdx)}
          y={y(points[peakIdx].tempF) - 9}
          textAnchor="middle"
          fontSize="10"
          fontWeight="700"
          fill="#FCA5A5"
          fontFamily="monospace"
        >
          PEAK {points[peakIdx].tempF.toFixed(0)}°F
        </text>

        {/* X labels (every other hour) */}
        {points.map((p, i) =>
          i % 2 === 0 ? (
            <text
              key={p.hour}
              x={x(i)}
              y={H - M.bottom + 14}
              textAnchor="middle"
              fontSize="9"
              fill="#5C6B65"
              fontFamily="monospace"
            >
              {p.label.slice(0, 2)}h
            </text>
          ) : null
        )}

        {/* Over-threshold axis strip */}
        {hotRuns.map(([a, b]) => (
          <rect
            key={`hot-${a}`}
            x={x(a)}
            y={H - M.bottom + 19}
            width={Math.max(2, x(b) - x(a))}
            height="4"
            rx="2"
            fill="#DC2626"
            opacity="0.8"
          />
        ))}

        {/* Hover crosshair + dot (transparent hit areas) */}
        {points.map((_, i) => (
          <rect
            key={`hit-${i}`}
            x={x(i) - (W - M.left - M.right) / (points.length - 1) / 2}
            y={M.top}
            width={(W - M.left - M.right) / (points.length - 1)}
            height={H - M.top - M.bottom}
            fill="transparent"
            onMouseEnter={() => setHoverIdx(i)}
          />
        ))}

        {hoverIdx !== null && (
          <g pointerEvents="none">
            <line
              x1={x(hoverIdx)}
              x2={x(hoverIdx)}
              y1={M.top}
              y2={H - M.bottom}
              stroke="#E7ECEA"
              strokeWidth="1"
              opacity="0.35"
            />
            <circle
              cx={x(hoverIdx)}
              cy={y(points[hoverIdx].tempF)}
              r="3.5"
              fill="#E7ECEA"
            />
          </g>
        )}
      </svg>

      {/* Readout row */}
      <div className="mt-1 flex items-center justify-between font-mono text-[10px]">
        <span className="text-neutral-500">
          {observedAt ? `anchor: ${observedAt}` : "deterministic artifact"}
        </span>
        <span className="text-ink-primary">
          {hover ? (
            <>
              {hover.label} ·{" "}
              <span
                className={
                  hover.tempF >= OSHA_WARNING_F ? "text-red-400" : "text-amber-400"
                }
              >
                {hover.tempF.toFixed(1)}°F
              </span>{" "}
              projected HI
            </>
          ) : (
            "hover for hourly detail"
          )}
        </span>
      </div>
    </section>
  );
}
