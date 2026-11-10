
/**
 * Typed API client + URL-persisted global filters.
 * Types are GENERATED from the backend's OpenAPI schema (lib/api-types.ts, `npm run gen:api`) — never hand-written.
 * All calls go through the server-side proxy (/api/proxy) — no credentials in the browser.
 */
import { useSearchParams } from "next/navigation";
import { useMemo } from "react";
import type { components } from "./api-types";

type S = components["schemas"];
export type Meta = S["Meta"];
export type Metric = S["Metric"];
export type TrendPoint = S["TrendPoint"];
export type Product = S["Product"];
export type SegmentRow = S["SegmentRow"];
export type Pareto = S["Pareto"];
export type Overview = S["OverviewResponse"];
export type Recommendation = S["Recommendation"];
export type BreakdownRow = S["BreakdownRow"];
export type ProductsResponse = S["ProductsResponse"];
export type SegmentsResponse = S["SegmentsResponse"];
export type RecommendationsResponse = S["RecommendationsResponse"];
export type AttributionCompareResponse = S["AttributionCompareResponse"];
export type AttributionRow = S["AttributionRow"];
export type DataQualityResponse = S["DataQualityResponse"];
export type FreshnessResponse = S["FreshnessResponse"];
export type TrendsResponse = S["TrendsResponse"];
export type ProductTrendResponse = S["ProductTrendResponse"];
export type ProductBreakdownResponse = S["ProductBreakdownResponse"];

export type RangeKey = "7" | "30" | "90";
export interface GlobalFilters {
  range: RangeKey; model: string; lookback: string; start: string; end: string;
}

const iso = (d: Date) => d.toISOString().slice(0, 10);

export function useGlobalFilters(): GlobalFilters {
  const sp = useSearchParams();
  const range = (["7", "30", "90"].includes(sp.get("range") ?? "") ? sp.get("range") : "30") as RangeKey;
  const model = /^M[1-4]$/.test(sp.get("attribution_model") ?? "") ? sp.get("attribution_model")! : "M1";
  const lookback = "7"; // the only window the marts compute (see backend SUPPORTED_LOOKBACK_DAYS)
  return useMemo(() => {
    const end = new Date(); end.setDate(end.getDate() - 1);
    const start = new Date(end); start.setDate(start.getDate() - (Number(range) - 1));
    return { range, model, lookback, start: iso(start), end: iso(end) };
  }, [range, model, lookback]);
}

export function filterQuery(f: GlobalFilters, extra: Record<string, string | number | undefined> = {}): string {
  const p = new URLSearchParams({
    start_date: f.start, end_date: f.end, attribution_model: f.model, lookback_days: f.lookback,
  });
  Object.entries(extra).forEach(([k, v]) => v !== undefined && v !== "" && p.set(k, String(v)));
  return p.toString();
}

export async function api<T>(path: string, qs = ""): Promise<T> {
  const res = await fetch(`/api/proxy/${path}${qs ? `?${qs}` : ""}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

export const exportUrl = (f: GlobalFilters, sort: string) =>
  `/api/proxy/api/v1/export/products.csv?${filterQuery(f, { sort })}`;
