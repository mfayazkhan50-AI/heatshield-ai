import type { LlmProvider, NodePhase, RiskTier } from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

/** Tier-4 BYOK provider registry — mirrors backend BYOK_PROVIDERS. */
export const BYOK_PROVIDERS: Array<{
  id: LlmProvider;
  label: string;
  placeholder: string;
}> = [
  { id: "groq", label: "Groq", placeholder: "gsk_..." },
  { id: "gemini", label: "Gemini", placeholder: "AIza..." },
  { id: "openai", label: "OpenAI", placeholder: "sk-..." },
  { id: "anthropic", label: "Anthropic", placeholder: "sk-ant-..." },
  { id: "deepseek", label: "DeepSeek", placeholder: "sk-..." },
];

export const DEMO_SITES = [
  { name: "Phoenix, AZ", lat: 33.4484, lon: -112.074 },
  { name: "Miami, FL", lat: 25.7617, lon: -80.1918 },
  { name: "Thermal, CA", lat: 33.635, lon: -116.135 },
] as const;

export const OPERATIONS = [
  {
    key: "construction",
    label: "Construction",
    hint: "Fixed site · moderate radiant load",
  },
  {
    key: "delivery",
    label: "Delivery",
    hint: "Mobile crews · A/C micro-breaks",
  },
  {
    key: "roadwork",
    label: "Roadwork",
    hint: "Asphalt radiant amplification +4°F",
  },
] as const;

/** LangGraph pipeline labels — order mirrors backend graph NODE_NAMES. */
export const NODE_LABELS: Record<string, string> = {
  ingest_environmental_data: "Ingest Environmental Data",
  evaluate_heat_risk: "Evaluate Heat Risk (Deterministic)",
  generate_compliance_plan: "Generate Compliance Plan (Grounded)",
  dispatch_critical_alerts: "Dispatch Critical Alerts (SMS/Voice)",
  format_enterprise_output: "Format Enterprise Output",
};

export const NODE_ORDER = Object.keys(NODE_LABELS);

// ---------------------------------------------------------------------------
// Brand status propagation — the whole UI follows this mapping
// ---------------------------------------------------------------------------

export const BRAND_STATUS: Record<
  RiskTier,
  { bgCls: string; borderCls: string; ringCls: string; hex: string }
> = {
  NORMAL: {
    bgCls: "bg-brand-normal/10",
    borderCls: "border-brand-normal/40",
    ringCls: "ring-brand-normal/40",
    hex: "#22C55E",
  },
  ELEVATED: {
    bgCls: "bg-brand-elevated/10",
    borderCls: "border-brand-elevated/40",
    ringCls: "ring-brand-elevated/40",
    hex: "#F59E0B",
  },
  HIGH: {
    bgCls: "bg-brand-high/10",
    borderCls: "border-brand-high/40",
    ringCls: "ring-brand-high/40",
    hex: "#F97316",
  },
  CRITICAL: {
    bgCls: "bg-brand-critical/10",
    borderCls: "border-brand-critical/50",
    ringCls: "ring-brand-critical/50",
    hex: "#DC2626",
  },
};

const RISK_TIER_ORDER: Record<string, number> = {
  NORMAL: 0,
  ELEVATED: 1,
  HIGH: 2,
  CRITICAL: 3,
};

/**
 * Derive the brand tier from whichever deterministic artifact is present.
 * Falls back through response-gap tier -> OSHA bin -> undefined.
 */
export function brandTierFrom(
  riskBreakdown?: { risk_tier?: RiskTier } | null,
  oshaRiskLevel?: string | null
): RiskTier | null {
  if (riskBreakdown?.risk_tier) return riskBreakdown.risk_tier;

  switch (oshaRiskLevel) {
    case "Low":
      return "NORMAL";
    case "Caution":
      return "ELEVATED";
    case "Danger":
      return "HIGH";
    case "Extreme Danger":
      return "CRITICAL";
    default:
      return null;
  }
}

export function severityRank(tier?: RiskTier | null): number {
  return tier ? RISK_TIER_ORDER[tier] ?? -1 : -1;
}

export const RISK_COLOR: Record<string, string> = {
  Low: "text-thermal-low",
  Caution: "text-thermal-caution",
  Warning: "text-thermal-warning",
  Danger: "text-thermal-danger",
  "Extreme Danger": "text-thermal-extreme",
};

const RISK_POSITION: Record<string, number> = {
  Low: 8,
  Caution: 30,
  Warning: 52,
  Danger: 74,
  "Extreme Danger": 94,
};

export function riskGaugePosition(riskLevel?: string): number {
  return riskLevel ? RISK_POSITION[riskLevel] ?? 50 : 0;
}

/** Location-derived thread id, e.g. "Miami, FL" -> "site-miami-fl". */
export function threadIdForSite(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
  return `site-${slug}`;
}

export const IDLE_NODE_PHASES = Object.fromEntries(
  NODE_ORDER.map((n) => [n, "idle"])
) as Record<string, NodePhase>;

export const COMPLETED_NODE_PHASES = Object.fromEntries(
  NODE_ORDER.map((n) => [n, "completed"])
) as Record<string, NodePhase>;
