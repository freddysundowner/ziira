import type { BadgeTone } from "@/sdk";

export const SEVERITY_TONE: Record<string, BadgeTone> = { info: "neutral", low: "info", medium: "warn", high: "bad", critical: "bad" };
export const EXCEPTION_STATUSES = ["open", "explained", "resolved", "dismissed"];
