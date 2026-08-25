"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type {
  HeatCell,
  HeatmapConnState,
  HeatmapResultPayload,
  OperationContext,
  PollProgress,
} from "@/lib/types";

export interface HeatmapStreamState {
  conn: HeatmapConnState;
  cells: HeatCell[];
  progress: PollProgress | null;
  fallback: { reason: string; message: string; attempts: number } | null;
  payload: HeatmapResultPayload | null;
  cacheHit: boolean;
  cacheLookupMs: number | null;
  latencyMs: number | null;
  error: string | null;
}

interface UseHeatmapStreamOptions {
  apiBaseUrl: string;
  /** Captured request identity; identity change triggers a new stream. */
  request: {
    location_name: string;
    latitude: number;
    longitude: number;
    operation_context: OperationContext;
    force_refresh?: boolean;
  } | null;
}

const EMPTY: HeatmapStreamState = {
  conn: "idle",
  cells: [],
  progress: null,
  fallback: null,
  payload: null,
  cacheHit: false,
  cacheLookupMs: null,
  latencyMs: null,
  error: null,
};

/**
 * Consumes the NDJSON progress stream from POST /api/heatmap?stream=1.
 * Every poll attempt, degradation and cell chunk is surfaced as state so
 * the UI can render live polling counters and the SIMULATED DATA banner.
 */
export function useHeatmapStream({
  apiBaseUrl,
  request,
}: UseHeatmapStreamOptions): HeatmapStreamState & { refetch: () => void } {
  const [state, setState] = useState<HeatmapStreamState>(EMPTY);
  const [nonce, setNonce] = useState(0);
  const abortRef = useRef<AbortController | null>(null);

  const refetch = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!request) {
      setState(EMPTY);
      return;
    }

    // Preserve the previous grid on refetch (30% opacity UX); only clear
    // when switching to a different site/operation entirely.
    setState((prev) =>
      prev.conn === "idle" || prev.payload === null
        ? { ...EMPTY, conn: "connecting" }
        : { ...prev, conn: "connecting", progress: null, error: null }
    );

    const controller = new AbortController();
    abortRef.current = controller;

    const startedAt = performance.now();
    (async () => {
      try {
        const res = await fetch(`${apiBaseUrl}/api/heatmap?stream=1`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...request,
            force_refresh:
              nonce > 0 ? true : (request.force_refresh ?? false),
          }),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          let message = `Heatmap request failed (${res.status})`;
          try {
            const err = await res.json();
            if (typeof err?.detail === "string") message = err.detail;
          } catch {
            /* keep default */
          }
          throw new Error(message);
        }

        setState((prev) => ({ ...prev, conn: "streaming" }));

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        const handleEvent = (raw: string) => {
          let event: Record<string, unknown>;
          try {
            event = JSON.parse(raw);
          } catch {
            return;
          }

          switch (event.type) {
            case "meta":
              break;

            case "cache":
              setState((prev) => ({
                ...prev,
                cacheHit: event.hit === true,
                cacheLookupMs:
                  typeof event.lookup_ms === "number"
                    ? (event.lookup_ms as number)
                    : prev.cacheLookupMs,
              }));
              break;

            case "progress":
              setState((prev) => ({
                ...prev,
                progress: event as unknown as PollProgress,
              }));
              break;

            case "fallback":
              setState((prev) => ({
                ...prev,
                fallback: {
                  reason: String(event.reason ?? "unavailable"),
                  message: String(event.message ?? "SIMULATED FIELD / DATA ACTIVE"),
                  attempts: Number(event.attempts ?? 0),
                },
              }));
              break;

            case "cells": {
              const batch = (event.cells as HeatCell[]) ?? [];
              const chunk = Number(event.chunk ?? 0);

              // Chunk 0 replaces (refetch reset); later chunks append.
              setState((prev) => ({
                ...prev,
                cells: chunk === 0 ? batch : [...prev.cells, ...batch],
              }));
              break;
            }

            case "result": {
              const payload = event.payload as HeatmapResultPayload;
              setState((prev) => ({
                ...prev,
                payload,
                latencyMs: Math.round(performance.now() - startedAt),
              }));
              break;
            }

            case "error":
              throw new Error(String(event.message ?? "stream error"));
          }
        };

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          let nl: number;

          while ((nl = buffer.indexOf("\n")) !== -1) {
            const line = buffer.slice(0, nl).trim();
            buffer = buffer.slice(nl + 1);
            if (line) handleEvent(line);
          }
        }

        if (buffer.trim()) handleEvent(buffer.trim());

        setState((prev) => ({
          ...prev,
          conn: prev.payload ? "done" : "error",
          error: prev.payload
            ? null
            : "Stream ended without a result frame.",
        }));
      } catch (err) {
        if (controller.signal.aborted) return;
        setState((prev) => ({
          ...prev,
          conn: "error",
          error: err instanceof Error ? err.message : "Connection error",
        }));
      }
    })();

    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiBaseUrl, JSON.stringify(request), nonce]);

  return { ...state, refetch };
}
