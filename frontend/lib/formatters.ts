/**
 * frontend/lib/formatters.ts
 * --------------------------
 * Number formatting utilities.
 * NULL/undefined → "—" (never show 0 or ∞ for missing ratios, DESIGN §11).
 * Currency: INR lakh/crore formatting by default (Q11 — adjust if international).
 */

const NULL_DISPLAY = "—";

/** Format any metric value; returns em-dash for null/undefined/NaN. */
export function fmt(
  value: number | null | undefined,
  options?: Intl.NumberFormatOptions
): string {
  if (value === null || value === undefined || isNaN(value)) return NULL_DISPLAY;
  return new Intl.NumberFormat("en-IN", options).format(value);
}

/** Currency — INR with lakh/crore formatting (e.g. ₹12.5L). */
export function fmtCurrency(value: number | null | undefined, currency = "INR"): string {
  if (value === null || value === undefined || isNaN(value)) return NULL_DISPLAY;

  if (currency === "INR") {
    if (Math.abs(value) >= 1e7) {
      return `₹${(value / 1e7).toFixed(2)}Cr`;
    }
    if (Math.abs(value) >= 1e5) {
      return `₹${(value / 1e5).toFixed(2)}L`;
    }
    if (Math.abs(value) >= 1000) {
      return `₹${(value / 1000).toFixed(1)}K`;
    }
    return `₹${value.toFixed(2)}`;
  }

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    notation: "compact",
  }).format(value);
}

/** Percentage, e.g. "3.24%" */
export function fmtPct(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || isNaN(value)) return NULL_DISPLAY;
  return `${(value * 100).toFixed(decimals)}%`;
}

/** ROAS, e.g. "2.34x" */
export function fmtRoas(value: number | null | undefined): string {
  if (value === null || value === undefined || isNaN(value)) return NULL_DISPLAY;
  return `${value.toFixed(2)}x`;
}

/** Large integer (impressions, clicks) — compact notation */
export function fmtCount(value: number | null | undefined): string {
  if (value === null || value === undefined || isNaN(value)) return NULL_DISPLAY;
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (value >= 1000) return `${(value / 1000).toFixed(1)}K`;
  return String(value);
}

/** Signed percentage delta, e.g. "+12.4%" */
export function fmtDelta(value: number | null | undefined): string {
  if (value === null || value === undefined || isNaN(value)) return NULL_DISPLAY;
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
}

/** "12 Oct" style short date from an ISO date string */
export function fmtShortDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}
