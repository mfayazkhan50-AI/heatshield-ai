"use client";

import { useState } from "react";
import { ChevronDown, KeyRound } from "lucide-react";
import { BYOK_PROVIDERS } from "@/lib/constants";
import type { LlmProvider } from "@/lib/types";

/**
 * BYOKPrompt
 * ==========
 * Noise-reduced key capture. Renders as a MINIMAL inline badge by default
 * (the deterministic plan is already on screen — no alarm needed); the
 * full form expands only when the user opts in. Same onSubmit contract
 * as before: (provider, key) → parent re-runs the stream.
 */
export default function BYOKPrompt({
  visible,
  onSubmit,
}: {
  visible: boolean;
  onSubmit: (provider: LlmProvider, key: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [provider, setProvider] = useState<LlmProvider>("groq");
  const [key, setKey] = useState("");

  if (!visible) return null;

  const placeholder =
    BYOK_PROVIDERS.find((p) => p.id === provider)?.placeholder ?? "key...";

  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="group flex w-full items-center gap-2 rounded-lg border border-hairline bg-panel/60 px-3 py-2 text-left transition hover:border-amber-500/50"
      >
        <KeyRound size={12} className="shrink-0 text-neutral-500 group-hover:text-amber-400" />
        <span className="min-w-0 flex-1 truncate font-mono text-[10px] uppercase tracking-wide text-neutral-500 group-hover:text-neutral-300">
          Tiers 1–3 exhausted · deterministic plan active
          <span className="ml-2 text-amber-400/80 opacity-0 transition-opacity group-hover:opacity-100">
            add a key for live reasoning
          </span>
        </span>
        <ChevronDown size={13} className="shrink-0 text-neutral-600 group-hover:text-amber-400" />
      </button>
    );
  }

  return (
    <div className="rounded-lg border border-amber-500/40 bg-amber-950/30 p-3">
      <div className="mb-2 flex items-center gap-2 text-xs uppercase tracking-widest text-amber-400">
        <KeyRound size={13} />
        Bring your own key — resume live reasoning
      </div>
      <p className="mb-3 text-xs text-amber-200/70">
        Hosted tiers hit their limit. Any supported provider unlocks live
        agentic narration; the deterministic plan below stays valid either way.
      </p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <select
          value={provider}
          onChange={(e) => setProvider(e.target.value as LlmProvider)}
          className="min-h-[44px] shrink-0 rounded border border-hairline bg-panel px-3 py-2 text-xs text-ink-primary sm:py-1.5"
        >
          {BYOK_PROVIDERS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label}
            </option>
          ))}
        </select>
        <input
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder={placeholder}
          className="min-h-[44px] min-w-0 flex-1 rounded border border-hairline bg-panel px-3 py-2 font-mono text-xs text-ink-primary placeholder:text-neutral-600"
        />
        <button
          onClick={() => {
            if (key.trim()) {
              onSubmit(provider, key.trim());
              setExpanded(false);
            }
          }}
          className="min-h-[44px] shrink-0 rounded bg-amber-600 px-4 py-2 text-xs font-medium text-white transition-all hover:bg-amber-500 active:bg-amber-700"
        >
          Resume
        </button>
      </div>
    </div>
  );
}
