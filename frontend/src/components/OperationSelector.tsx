"use client";

import { HardHat } from "lucide-react";
import { OPERATIONS } from "@/lib/constants";
import type { OperationContext } from "@/lib/types";

/**
 * OperationSelector — stacked radio list for the operation profile.
 * Full-width rows keep label + hint legible even in the narrow sidebar.
 *
 * Contrast hierarchy:
 *   active   → vivid amber border-2, radial glow backdrop, ping dot
 *   inactive → muted dark-gray, transparent border, neutral-700 hover
 */
export default function OperationSelector({
  value,
  disabled = false,
  onChange,
}: {
  value: OperationContext;
  disabled?: boolean;
  onChange: (op: OperationContext) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Operation context"
      className="space-y-1 rounded-lg border border-hairline bg-void/60 p-1"
    >
      {OPERATIONS.map((op) => {
        const active = op.key === value;

        return (
          <button
            key={op.key}
            role="radio"
            aria-checked={active}
            disabled={disabled}
            onClick={() => onChange(op.key)}
            title={op.hint}
            className={`flex min-h-[40px] w-full items-center gap-2.5 rounded-md border px-2.5 py-1.5 text-left transition-all duration-150 ${
              active
                ? "border-2 border-amber-500/80 bg-amber-500/10 shadow-[0_0_15px_rgba(245,158,11,0.2)]"
                : "border border-transparent bg-neutral-900/60 text-neutral-400 hover:border-neutral-700"
            } ${disabled ? "cursor-not-allowed opacity-50" : ""}`}
          >
            <HardHat
              size={14}
              className={`shrink-0 ${active ? "text-amber-400" : "text-neutral-500"}`}
            />
            <span className="min-w-0 flex-1">
              <span
                className={`block truncate font-mono text-[11px] font-semibold uppercase tracking-wide ${
                  active ? "text-amber-400" : "text-neutral-300"
                }`}
              >
                {op.label}
              </span>
              <span
                className={`block truncate text-[9px] ${
                  active ? "text-amber-200/60" : "text-neutral-500"
                }`}
              >
                {op.hint}
              </span>
            </span>
            {active && (
              <span className="relative flex h-2 w-2 shrink-0">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-400 shadow-[0_0_8px_rgba(245,158,11,0.9)]" />
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
