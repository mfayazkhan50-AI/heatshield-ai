"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Crosshair, Layers, MousePointer2 } from "lucide-react";
import type { HeatCell, HeatmapResultPayload } from "@/lib/types";

/**
 * ThermalCanvasMap
 * ================
 * Georeferenced street-level thermal field renderer.
 *
 * Layer stack (painted back-to-front into one dpr-aware offscreen raster,
 * then blitted — pan/zoom stays at display refresh rate):
 *
 *   1. CARTO Dark Matter raster base tiles (Web-Mercator slippy scheme,
 *      no SDK/key needed) — streets, highways and labels.
 *   2. Thermal field overlay in a two-pass blend (see below) so road
 *      geometry, highway names and building vectors stay legible.
 *
 * Zero npm dependencies: tiles are plain <img> fetches; projection is
 * standard Web-Mercator math. If tiles are unreachable (offline judge
 * laptop) the map degrades to a dark graticule — the field stays exact.
 */

/**
 * Thermal overlay blending strategy (street-visibility fix):
 *
 * Pass 1 — CRITICAL halos painted with `screen` compositing so hot zones
 *          LUMINATE without burying the base map.
 * Pass 2 — full field painted with `multiply` at THERMAL_ALPHA: multiply
 *          keeps dark CARTO street lines / building vectors dark through
 *          the heat fill, and light highway labels stay readable — the
 *          canvas-native equivalent of CSS mix-blend-mode: multiply,
 *          without cross-layer CSS blending cost.
 */
const THERMAL_ALPHA = 0.5;
const GLOW_ALPHA = 0.36;

/** fitBounds-style padding (px) around the thermal BBOX. */
const FIT_PADDING_PX = 20;
/** Professional cap so street-level grids never zoom into pixel mush. */
const FIT_MAX_ZOOM = 15;

const TILE_SUBDOMAINS = ["a", "b", "c"] as const;
let TILE_SUBDOMAIN_IDX = 0;

const CELL_COLORS: Record<HeatCell["class"], string> = {
  SAFE: "#164E63",
  WARM: "#A16207",
  HOT: "#C2410C",
  CRITICAL: "#DC2626",
};

// ---------------------------------------------------------------------------
// Web-Mercator helpers (unit square world space, y down)
// ---------------------------------------------------------------------------

const lonToWorldX = (lon: number): number => (lon + 180) / 360;

const latToWorldY = (lat: number): number => {
  const s = Math.sin((Math.max(-85.05, Math.min(85.05, lat)) * Math.PI) / 180);
  return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI);
};

interface View {
  cx: number; // world-x fraction at viewport center
  cy: number; // world-y fraction
  zoom: number; // fractional tile zoom
}

interface TileEntry {
  img: HTMLImageElement;
  status: "loading" | "ready" | "failed";
}

export default function ThermalCanvasMap({
  cells,
  payload,
  refetching = false,
  fitKey,
}: {
  cells: HeatCell[];
  payload?: HeatmapResultPayload | null;
  refetching?: boolean;
  /** Change of this key re-fits the viewport to the data (site/op switch). */
  fitKey?: string;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const offscreenRef = useRef<HTMLCanvasElement | null>(null);
  const viewRef = useRef<View>({ cx: 0.5, cy: 0.5, zoom: 12 });
  const dirtyRef = useRef(true);
  const rafRef = useRef<number | null>(null);
  const tilesRef = useRef<Map<string, TileEntry>>(new Map());
  const tilesFailedRef = useRef(false);
  const tilesLoadedRef = useRef(false);

  const dragRef = useRef<{ active: boolean; lastX: number; lastY: number }>({
    active: false,
    lastX: 0,
    lastY: 0,
  });

  const [hovered, setHovered] = useState<{
    cell: HeatCell;
    px: number;
    py: number;
  } | null>(null);
  const [offline, setOffline] = useState(false);

  /** World-fraction bounds of the thermal grid. */
  const bounds = useMemo(() => {
    if (!cells.length) return null;

    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;

    for (const c of cells) {
      const wx = lonToWorldX(c.lon);
      const wy = latToWorldY(c.lat);
      if (wx < minX) minX = wx;
      if (wx > maxX) maxX = wx;
      if (wy < minY) minY = wy;
      if (wy > maxY) maxY = wy;
    }

    return { minX, maxX, minY, maxY };
  }, [cells]);

  // ------------------------------------------------------------------
  // Projection — lat/lon to CSS pixels under the current view
  // ------------------------------------------------------------------

  const project = useCallback(
    (lat: number, lon: number, cssW: number, cssH: number): [number, number] => {
      const worldPx = 256 * Math.pow(2, viewRef.current.zoom);
      const v = viewRef.current;
      return [
        (lonToWorldX(lon) - v.cx) * worldPx + cssW / 2,
        (latToWorldY(lat) - v.cy) * worldPx + cssH / 2,
      ];
    },
    []
  );

  const unproject = useCallback(
    (sx: number, sy: number, cssW: number, cssH: number): [number, number] => {
      const worldPx = 256 * Math.pow(2, viewRef.current.zoom);
      const v = viewRef.current;
      return [
        (sx - cssW / 2) / worldPx + v.cx,
        (sy - cssH / 2) / worldPx + v.cy,
      ];
    },
    []
  );

  // ------------------------------------------------------------------
  // Base tiles — CARTO Dark Matter slippy scheme
  // ------------------------------------------------------------------

  const requestTile = useCallback((key: string, z: number, x: number, y: number) => {
    const cache = tilesRef.current;

    if (cache.size > 160) cache.clear();

    const sub = TILE_SUBDOMAINS[TILE_SUBDOMAIN_IDX++ % TILE_SUBDOMAINS.length];
    const img = new Image();
    img.decoding = "async";

    const entry: TileEntry = { img, status: "loading" };
    cache.set(key, entry);

    img.onload = () => {
      entry.status = "ready";
      tilesLoadedRef.current = true;
      dirtyRef.current = true;
    };
    img.onerror = () => {
      entry.status = "failed";
      tilesFailedRef.current = true;
      setOffline(true);
      dirtyRef.current = true;
    };

    img.src = `https://${sub}.basemaps.cartocdn.com/dark_all/${z}/${x}/${y}.png`;
  }, []);

  const drawBaseTiles = useCallback(
    (
      ctx: CanvasRenderingContext2D,
      cssW: number,
      cssH: number
    ): void => {
      const v = viewRef.current;
      const worldPx = 256 * Math.pow(2, v.zoom);
      const z = Math.min(18, Math.max(2, Math.floor(v.zoom)));
      const nTiles = Math.pow(2, z);
      const tileSize = 256 * Math.pow(2, v.zoom - z);

      const wx0 = v.cx - cssW / 2 / worldPx;
      const wx1 = v.cx + cssW / 2 / worldPx;
      const wy0 = Math.max(0, v.cy - cssH / 2 / worldPx);
      const wy1 = Math.min(1, v.cy + cssH / 2 / worldPx);

      const tx0 = Math.floor(wx0 * nTiles);
      const tx1 = Math.floor(wx1 * nTiles);
      const ty0 = Math.floor(wy0 * nTiles);
      const ty1 = Math.floor(wy1 * nTiles);

      // Cap pathological tile counts at extreme zoom-outs.
      if ((tx1 - tx0 + 1) * (ty1 - ty0 + 1) > 144) return;

      for (let ty = ty0; ty <= ty1; ty++) {
        for (let tx = tx0; tx <= tx1; tx++) {
          const wrappedX = ((tx % nTiles) + nTiles) % nTiles;
          const key = `${z}/${wrappedX}/${ty}`;

          let entry = tilesRef.current.get(key);
          if (!entry) {
            requestTile(key, z, wrappedX, ty);
            entry = tilesRef.current.get(key)!;
          }

          const px = (tx / nTiles - v.cx) * worldPx + cssW / 2;
          const py = (ty / nTiles - v.cy) * worldPx + cssH / 2;

          if (entry.status === "ready") {
            // Half-pixel overlap hides seam artifacts between tiles.
            ctx.drawImage(entry.img, px, py, tileSize + 0.5, tileSize + 0.5);
          } else {
            ctx.fillStyle = "#0F1418";
            ctx.fillRect(px, py, tileSize, tileSize);
          }
        }
      }
    },
    [requestTile]
  );

  // ------------------------------------------------------------------
  // Offscreen raster painting — tiles, then blended thermal overlay
  // ------------------------------------------------------------------

  const paintRaster = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas || !bounds || !cells.length) return;

    const cssW = canvas.clientWidth;
    const cssH = canvas.clientHeight;
    if (!cssW || !cssH) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    let off = offscreenRef.current;
    if (!off) {
      off = document.createElement("canvas");
      offscreenRef.current = off;
    }
    off.width = Math.floor(cssW * dpr);
    off.height = Math.floor(cssH * dpr);

    const ctx = off.getContext("2d");
    if (!ctx) return;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);
    ctx.fillStyle = "#0A0D0F";
    ctx.fillRect(0, 0, cssW, cssH);

    // Layer 1 — geographic base.
    drawBaseTiles(ctx, cssW, cssH);

    if (tilesFailedRef.current && !tilesLoadedRef.current) {
      // Offline fallback: subtle graticule so surface never looks broken.
      ctx.strokeStyle = "rgba(56,68,64,0.35)";
      ctx.lineWidth = 1;
      for (let gx = 0; gx < cssW; gx += 48) {
        ctx.beginPath();
        ctx.moveTo(gx, 0);
        ctx.lineTo(gx, cssH);
        ctx.stroke();
      }
      for (let gy = 0; gy < cssH; gy += 48) {
        ctx.beginPath();
        ctx.moveTo(0, gy);
        ctx.lineTo(cssW, gy);
        ctx.stroke();
      }
    }

    // Layer 2 — thermal field, globally blended over the base map.
    const v = viewRef.current;
    const worldPx = 256 * Math.pow(2, v.zoom);

    const spanXf = Math.max(bounds.maxX - bounds.minX, 1e-9);
    const spanYf = Math.max(bounds.maxY - bounds.minY, 1e-9);
    const n = Math.round(Math.sqrt(cells.length));
    const cellW = (spanXf * worldPx) / n;
    const cellH = (spanYf * worldPx) / n;
    const gapX = cellW * 0.08;
    const gapY = cellH * 0.08;

    // Pass 1 — CRITICAL halos: `screen` compositing makes hot zones
    // luminous over the dark base map without smothering street detail.
    ctx.globalAlpha = GLOW_ALPHA;
    ctx.globalCompositeOperation = "screen";

    for (const cell of cells) {
      if (cell.class !== "CRITICAL") continue;

      const [x, y] = project(cell.lat, cell.lon, cssW, cssH);

      ctx.fillStyle = CELL_COLORS.CRITICAL;
      ctx.shadowColor = "rgba(220, 38, 38, 0.85)";
      ctx.shadowBlur = Math.max(6, cellW * 0.45);
      ctx.fillRect(x - cellW / 2, y - cellH / 2, cellW - gapX, cellH - gapY);
    }

    // Pass 2 — full field: `multiply` wash. Dark CARTO linework stays
    // dark through the heat fill; light highway labels remain readable.
    ctx.shadowBlur = 0;
    ctx.globalAlpha = THERMAL_ALPHA;
    ctx.globalCompositeOperation = "multiply";

    for (const cell of cells) {
      const [x, y] = project(cell.lat, cell.lon, cssW, cssH);

      ctx.fillStyle = CELL_COLORS[cell.class];
      ctx.fillRect(x - cellW / 2, y - cellH / 2, cellW - gapX, cellH - gapY);
    }

    // Restore default compositing for subsequent layers.
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;

    dirtyRef.current = true;
  }, [bounds, cells, drawBaseTiles, project]);

  // ------------------------------------------------------------------
  // Viewport fitting
  // ------------------------------------------------------------------

  /**
   * fitBounds equivalent with COVER semantics: the thermal BBOX fills the
   * entire viewer canvas edge-to-edge (max of the per-axis zooms, ~20px
   * padding), so the field reads as a seamless spatial-intelligence layer
   * over the street network instead of a floating box. Capped at z15.
   */
  const fitView = useCallback(
    (cssW: number, cssH: number) => {
      if (!bounds) return;

      const spanXf = Math.max(bounds.maxX - bounds.minX, 1e-9);
      const spanYf = Math.max(bounds.maxY - bounds.minY, 1e-9);

      const usableW = Math.max(120, cssW - FIT_PADDING_PX * 2);
      const usableH = Math.max(120, cssH - FIT_PADDING_PX * 2);

      const zoomX = Math.log2(usableW / (256 * spanXf));
      const zoomY = Math.log2(usableH / (256 * spanYf));

      viewRef.current = {
        cx: (bounds.minX + bounds.maxX) / 2,
        cy: Math.max(0.01, Math.min(0.99, (bounds.minY + bounds.maxY) / 2)),
        zoom: Math.min(FIT_MAX_ZOOM, Math.max(3, Math.max(zoomX, zoomY))),
      };

      dirtyRef.current = true;
    },
    [bounds]
  );

  // ------------------------------------------------------------------
  // Render loop — blit only when dirty
  // ------------------------------------------------------------------

  useEffect(() => {
    const loop = () => {
      const canvas = canvasRef.current;

      if (canvas && dirtyRef.current) {
        const dpr = Math.min(window.devicePixelRatio || 1, 2);

        if (
          canvas.width !== Math.floor(canvas.clientWidth * dpr) ||
          canvas.height !== Math.floor(canvas.clientHeight * dpr)
        ) {
          canvas.width = Math.floor(canvas.clientWidth * dpr);
          canvas.height = Math.floor(canvas.clientHeight * dpr);
          paintRaster();
        }

        const ctx = canvas.getContext("2d");

        if (ctx) {
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          ctx.clearRect(0, 0, canvas.width, canvas.height);

          const off = offscreenRef.current;
          if (off) {
            ctx.drawImage(off, 0, 0);
            dirtyRef.current = false;
          }
        }
      }

      rafRef.current = requestAnimationFrame(loop);
    };

    rafRef.current = requestAnimationFrame(loop);

    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [paintRaster]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !bounds || !cells.length) return;

    const cssW = canvas.clientWidth;
    const cssH = canvas.clientHeight;
    if (cssW && cssH) {
      fitView(cssW, cssH);
      paintRaster();
      dirtyRef.current = true;
    }
  }, [cells, bounds, fitKey, fitView, paintRaster]);

  useEffect(() => {
    const onResize = () => {
      paintRaster();
      dirtyRef.current = true;
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [paintRaster]);

  /**
   * Robustness net: repaint when the surface resizes 0 -> N or re-enters
   * the viewport after scroll, so the field never renders blank.
   */
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap || typeof ResizeObserver === "undefined") return;

    let lastW = 0;
    let lastH = 0;

    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;

      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0 && (width !== lastW || height !== lastH)) {
        lastW = width;
        lastH = height;
        paintRaster();
        dirtyRef.current = true;
      }
    });
    ro.observe(wrap);

    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          paintRaster();
          dirtyRef.current = true;
        }
      },
      { threshold: 0.05 }
    );
    io.observe(wrap);

    return () => {
      ro.disconnect();
      io.disconnect();
    };
  }, [paintRaster]);

  // ------------------------------------------------------------------
  // Interaction — mercator-correct zoom-around-cursor + drag pan
  // ------------------------------------------------------------------

  const onWheel = useCallback(
    (e: React.WheelEvent<HTMLCanvasElement>) => {
      e.preventDefault();

      const canvas = canvasRef.current;
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const my = e.clientY - rect.top;

      const cssW = rect.width;
      const cssH = rect.height;

      const [wxBefore, wyBefore] = unproject(mx, my, cssW, cssH);

      const factor = e.deltaY < 0 ? 1.18 : 1 / 1.18;
      const v = viewRef.current;
      v.zoom = Math.min(18, Math.max(3, v.zoom + Math.log2(factor)));

      const [wxAfter, wyAfter] = unproject(mx, my, cssW, cssH);
      v.cx += wxBefore - wxAfter;
      v.cy = Math.max(0.01, Math.min(0.99, v.cy + wyBefore - wyAfter));

      paintRaster();
      dirtyRef.current = true;
    },
    [paintRaster, unproject]
  );

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      dragRef.current = { active: true, lastX: e.clientX, lastY: e.clientY };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    []
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();

      if (!dragRef.current.active) {
        // Hover readout: nearest cell to the georeferenced cursor.
        if (!cells.length) return;

        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;

        const cssW = rect.width;
        const cssH = rect.height;

        let best: HeatCell | null = null;
        let bestDist = Infinity;

        const hitRadius =
          Math.min(cssW, cssH) *
          0.05 *
          Math.pow(1.5, Math.min(4, Math.max(0, viewRef.current.zoom - 12)));

        for (const cell of cells) {
          const [cx, cy] = project(cell.lat, cell.lon, cssW, cssH);
          const d = (cx - mx) * (cx - mx) + (cy - my) * (cy - my);
          if (d < bestDist) {
            bestDist = d;
            best = cell;
          }
        }

        setHovered(best && bestDist <= hitRadius * hitRadius
          ? { cell: best, px: mx, py: my }
          : null);
        return;
      }

      const v = viewRef.current;
      const worldPx = 256 * Math.pow(2, v.zoom);

      v.cx -= (e.clientX - dragRef.current.lastX) / worldPx;
      v.cy = Math.max(
        0.01,
        Math.min(0.99, v.cy - (e.clientY - dragRef.current.lastY) / worldPx)
      );

      dragRef.current.lastX = e.clientX;
      dragRef.current.lastY = e.clientY;

      paintRaster();
      dirtyRef.current = true;
    },
    [cells, paintRaster, project]
  );

  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      dragRef.current.active = false;
      e.currentTarget.releasePointerCapture(e.pointerId);
    },
    []
  );

  const resetView = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    fitView(canvas.clientWidth, canvas.clientHeight);
    paintRaster();
    dirtyRef.current = true;
  }, [fitView, paintRaster]);

  // ------------------------------------------------------------------
  // Render
  // ------------------------------------------------------------------

  const criticalPct =
    payload && payload.tile_count > 0
      ? Math.round((payload.critical_cells / payload.tile_count) * 100)
      : null;

  return (
    <div
      ref={wrapRef}
      className="relative h-[440px] overflow-hidden rounded-lg border border-hairline bg-void sm:h-[560px]"
    >
      {/* Header strip */}
      <div className="absolute inset-x-0 top-0 z-20 flex items-center justify-between gap-2 border-b border-hairline bg-panel/85 px-3 py-2 backdrop-blur">
        <span className="flex items-center gap-2 text-[10px] uppercase tracking-widest text-ink-secondary sm:text-xs">
          <Layers size={13} className="text-brand-elevated" />
          Street-Level Thermal Field · CARTO Dark
        </span>

        <div className="flex items-center gap-2 font-mono text-[10px] text-ink-muted">
          <button
            onClick={resetView}
            title="Reset view"
            className="flex items-center gap-1 rounded border border-hairline px-2 py-1 transition hover:border-brand-elevated hover:text-brand-elevated"
          >
            <Crosshair size={11} />
            reset
          </button>
          {criticalPct !== null && (
            <span
              className={`rounded px-2 py-1 ${
                criticalPct > 50
                  ? "bg-brand-critical/15 text-brand-critical"
                  : criticalPct > 10
                    ? "bg-brand-high/15 text-brand-high"
                    : "bg-thermal-low/15 text-thermal-low"
              }`}
            >
              ≥40°C cells: {criticalPct}%
            </span>
          )}
        </div>
      </div>

      {/* Canvas surface */}
      <div className="absolute inset-0 pt-9">
        <canvas
          ref={canvasRef}
          onWheel={onWheel}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          className={`h-full w-full cursor-grab active:cursor-grabbing touch-none transition-opacity duration-500 ${
            refetching ? "opacity-30" : "opacity-100"
          }`}
        />
      </div>

      {/* Empty state */}
      {!cells.length && (
        <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 text-center">
          <MousePointer2 size={22} className="text-ink-muted" />
          <p className="max-w-xs text-sm text-ink-muted">
            Run the heat intelligence pipeline to render the street-level
            thermal field.
          </p>
        </div>
      )}

      {/* Hover tooltip */}
      {hovered && (
        <div
          className="pointer-events-none absolute z-30 rounded border border-hairline bg-panel-raised/95 px-2.5 py-1.5 font-mono text-[10px] shadow-xl"
          style={{
            left: hovered.px + 12,
            top: hovered.py + 12,
          }}
        >
          <span
            className={
              hovered.cell.class === "CRITICAL"
                ? "text-brand-critical"
                : hovered.cell.class === "HOT"
                  ? "text-thermal-danger"
                  : "text-ink-primary"
            }
          >
            {hovered.cell.temp_f.toFixed(1)}°F / {hovered.cell.temp_c.toFixed(1)}°C
          </span>
          <span className="ml-2 text-ink-muted">{hovered.cell.class}</span>
        </div>
      )}

      {/* Legend */}
      <div className="absolute bottom-3 left-3 z-20 flex flex-wrap items-center gap-x-3 gap-y-1 rounded border border-hairline bg-panel/85 px-3 py-2 font-mono text-[9px] uppercase tracking-wide text-ink-muted backdrop-blur">
        {(Object.keys(CELL_COLORS) as HeatCell["class"][]).map((k) => (
          <span key={k} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-2.5 rounded-sm"
              style={{ backgroundColor: CELL_COLORS[k], opacity: k === "SAFE" ? 1 : 0.78 }}
            />
            {k === "CRITICAL" ? "≥40°C" : k}
          </span>
        ))}
      </div>

      {/* Attribution + connectivity status (CARTO/OSM terms) */}
      <div className="absolute bottom-3 right-3 z-20 flex flex-col items-end gap-1">
        {offline && (
          <span className="rounded border border-hairline bg-panel/85 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide text-thermal-caution backdrop-blur">
            tiles offline · field exact
          </span>
        )}
        <span className="rounded bg-black/50 px-1.5 py-0.5 font-mono text-[8px] text-ink-muted backdrop-blur">
          © OpenStreetMap contributors © CARTO
        </span>
      </div>
    </div>
  );
}
