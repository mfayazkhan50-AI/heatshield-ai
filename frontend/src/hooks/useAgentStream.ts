"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { IDLE_NODE_PHASES, NODE_LABELS } from "@/lib/constants";
import type {
  AgentResponse,
  AgentRunSummary,
  AgentStreamParams,
  ConnState,
  LogLine,
  NodePhase,
} from "@/lib/types";

const EMPTY_RESPONSE: AgentResponse = {
  enterprise_output: null,
  awaiting_byok: false,
  active_tier: null,
  tier_trace: [],
  node_log: [],
};

interface UseAgentStreamOptions {
  apiBaseUrl: string;
  /**
   * The exact request for the current run, captured at trigger time.
   * Pass `null` to stay/reset to idle. Changing this object identity
   * starts a new run — every parameter in it is passed verbatim into
   * the POST request body, so a location switch can never reuse
   * stale values.
   */
  params: AgentStreamParams | null;
  /** Called once per successful run with a cacheable snapshot. */
  onComplete?: (summary: AgentRunSummary) => void;
}

interface RunBuffer {
  nodePhases: Record<string, NodePhase>;
  log: LogLine[];
  tokenTrace: string;
  response: AgentResponse | null;
  rawResultJson: string | null;
}

/**
 * Extract one SSE logical frame's event name + joined data payload.
 * Comment/keep-alive lines (`: ping`) are ignored per the SSE spec.
 */
function parseSseFrame(frame: string): { event: string; data: string } | null {
  let eventName = "";
  const dataLines: string[] = [];

  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) continue;
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""));
    }
  }

  if (!eventName && dataLines.length === 0) return null;

  return { event: eventName || "message", data: dataLines.join("\n") };
}

export function useAgentStream({
  apiBaseUrl,
  params,
  onComplete,
}: UseAgentStreamOptions) {
  const [nodePhases, setNodePhases] =
    useState<Record<string, NodePhase>>(IDLE_NODE_PHASES);
  const [log, setLog] = useState<LogLine[]>([]);
  const [tokenTrace, setTokenTrace] = useState("");
  const [connState, setConnState] = useState<ConnState>("idle");
  const [response, setResponse] = useState<AgentResponse | null>(null);
  const [rawResultJson, setRawResultJson] = useState<string | null>(null);

  const onCompleteRef = useRef(onComplete);
  useEffect(() => {
    onCompleteRef.current = onComplete;
  });

  const bufferRef = useRef<RunBuffer>({
    nodePhases: IDLE_NODE_PHASES,
    log: [],
    tokenTrace: "",
    response: null,
    rawResultJson: null,
  });

  const pushLog = useCallback((text: string, kind: LogLine["kind"]) => {
    const line: LogLine = {
      id: `${Date.now()}-${Math.random()}`,
      text,
      kind,
    };
    bufferRef.current.log.push(line);
    setLog((prev) => [...prev.slice(-199), line]);
  }, []);

  useEffect(() => {
    if (!params) {
      setNodePhases(IDLE_NODE_PHASES);
      setLog([]);
      setTokenTrace("");
      setConnState("idle");
      setResponse(null);
      setRawResultJson(null);
      return;
    }

    // Reset per-run UI state
    setNodePhases(IDLE_NODE_PHASES);
    setLog([]);
    setTokenTrace("");
    setConnState("connecting");
    setResponse(null);
    setRawResultJson(null);

    bufferRef.current = {
      nodePhases: { ...IDLE_NODE_PHASES },
      log: [],
      tokenTrace: "",
      response: null,
      rawResultJson: null,
    };

    // ---------------------------------------------------------------
    // POST-based SSE streaming.
    //
    // Native EventSource only supports GET, which would put BYOK
    // credentials in the query string — leaking them into uvicorn
    // access logs, browser history, and proxies. Standard fetch with
    // a ReadableStream lets us POST the parameters as an encrypted
    // JSON body while still consuming the same SSE event frames.
    // ---------------------------------------------------------------

    const controller = new AbortController();
    let sawTerminalEvent = false;

    const finishRun = () => {
      sawTerminalEvent = true;
      setConnState("done");
      onCompleteRef.current?.({
        params,
        response: bufferRef.current.response ?? EMPTY_RESPONSE,
        nodePhases: { ...bufferRef.current.nodePhases },
        log: [...bufferRef.current.log],
        tokenTrace: bufferRef.current.tokenTrace,
        rawResultJson: bufferRef.current.rawResultJson,
      });
    };

    const failRun = (message: string) => {
      sawTerminalEvent = true;
      setConnState("error");
      pushLog(message, "error");
    };

    let pendingFrames = "";

    const handleEvent = (eventName: string, data: string) => {
      switch (eventName) {
        case "status": {
          const parsed = JSON.parse(data) as {
            phase?: string;
            thread_id?: string;
          };
          if (parsed.phase === "start") {
            setConnState("streaming");
            pushLog(
              `Agent run started for thread ${parsed.thread_id}`,
              "status"
            );
          } else if (parsed.phase === "complete") {
            pushLog("Agent run complete.", "status");
            finishRun();
            controller.abort();
          }
          break;
        }

        case "node": {
          const parsed = JSON.parse(data) as {
            name: string;
            phase: string;
            status: string;
          };
          const nextPhase: NodePhase =
            parsed.status === "running" ? "running" : "completed";
          bufferRef.current.nodePhases[parsed.name] = nextPhase;
          setNodePhases((prev) => ({ ...prev, [parsed.name]: nextPhase }));
          pushLog(
            `${NODE_LABELS[parsed.name] ?? parsed.name} — ${
              parsed.phase === "start" ? "started" : "completed"
            }`,
            "node"
          );
          break;
        }

        case "token": {
          const parsed = JSON.parse(data) as { text?: string };
          if (parsed.text) {
            const next = `${bufferRef.current.tokenTrace}${parsed.text}`.slice(
              -2000
            );
            bufferRef.current.tokenTrace = next;
            setTokenTrace(next);
          }
          break;
        }

        case "result": {
          const parsed = JSON.parse(data) as AgentResponse;
          bufferRef.current.response = parsed;
          bufferRef.current.rawResultJson = data;
          setResponse(parsed);
          setRawResultJson(data);
          if (parsed.enterprise_output) {
            pushLog(
              `Compliance plan generated via ${parsed.active_tier}.`,
              "status"
            );
          }
          if (parsed.awaiting_byok) {
            pushLog(
              "Hosted tiers exhausted — deterministic plan active. BYOK unlocks live reasoning.",
              "status"
            );
          }
          break;
        }

        case "error": {
          let message = "Connection error";
          try {
            const parsed = JSON.parse(data) as { message?: string };
            message = parsed.message ?? message;
          } catch {
            /* non-JSON error payload — keep default message */
          }
          failRun(message);
          break;
        }
      }
    };

    const consumeChunk = (chunk: string) => {
      // Normalize CRLF/CR line endings to LF for uniform frame splitting
      const normalized = chunk.replace(/\r\n/g, "\n").replace(/\r/g, "\n");

      pendingFrames += normalized;

      let boundary = pendingFrames.indexOf("\n\n");
      while (boundary !== -1) {
        const frame = parseSseFrame(pendingFrames.slice(0, boundary));
        pendingFrames = pendingFrames.slice(boundary + 2);
        if (frame) handleEvent(frame.event, frame.data);
        boundary = pendingFrames.indexOf("\n\n");
      }
    };

    (async () => {
      try {
        const res = await fetch(`${apiBaseUrl}/api/stream-agent`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(params),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          let message = `Request failed with status ${res.status}`;
          try {
            const errJson = await res.json();
            const detail = errJson?.detail;
            if (typeof detail === "string") {
              message = detail;
            } else if (Array.isArray(detail)) {
              message = detail
                .map((d: { msg?: string }) => d?.msg ?? JSON.stringify(d))
                .join("; ");
            }
          } catch {
            /* non-JSON error body — keep default message */
          }
          throw new Error(message);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          consumeChunk(decoder.decode(value, { stream: true }));
        }

        // Server closed the stream. If no terminal SSE event arrived
        // (missing complete/error), surface a clean end instead of a
        // spinner that hangs forever.
        if (!sawTerminalEvent) {
          setConnState("done");
        }
      } catch (err) {
        // Aborts come from unmount, param changes, or a terminal SSE
        // event closing the connection early — those are already handled.
        if (controller.signal.aborted) return;
        failRun(err instanceof Error ? err.message : "Connection error");
      }
    })();

    return () => {
      controller.abort();
    };
  }, [params, apiBaseUrl, pushLog]);

  return { nodePhases, log, tokenTrace, connState, response, rawResultJson };
}
