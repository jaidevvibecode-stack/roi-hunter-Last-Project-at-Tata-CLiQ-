"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { api, filterQuery, useGlobalFilters, type Product, type ProductBreakdownResponse, type ProductTrendResponse } from "@/lib/api";
import { fmtCount, fmtCurrency, fmtPct, fmtRoas, fmtShortDate } from "@/lib/formatters";
import { Chart, areaOption } from "./charts";
import { Skeleton } from "./ui";

export function ProductDrawer({ product, onClose }: { product: Product; onClose: () => void }) {
  const f = useGlobalFilters();
  const [by, setBy] = useState<"campaign" | "adset" | "ad">("campaign");
  const base = `api/v1/products/${encodeURIComponent(product.product_key)}`;

  const trend = useQuery({
    queryKey: ["ptrend", product.product_key, f],
    queryFn: () => api<ProductTrendResponse>(`${base}/trend`, filterQuery(f)),
  });
  const bd = useQuery({
    queryKey: ["pbreak", product.product_key, f, by],
    queryFn: () => api<ProductBreakdownResponse>(`${base}/breakdown`, filterQuery(f, { by })),
  });

  return (
    <div className="fixed inset-0 z-50 flex justify-end" onClick={onClose}>
      <div className="absolute inset-0 bg-black/70" />
      <aside className="card relative w-[560px] max-w-full h-full overflow-auto p-6 fade-in rounded-r-none"
        style={{ background: "#08080a" }} onClick={(e) => e.stopPropagation()}>
        <button className="absolute right-4 top-4 pill" onClick={onClose} aria-label="Close"><X size={13} /></button>
        <p className="muted text-xs">{product.retailer_id} · {product.brand} · {product.category}</p>
        <h2 className="text-xl font-bold mt-1 pr-12">{product.product_name}</h2>

        <div className="grid grid-cols-3 gap-2 mt-5">
          {([["Spend", fmtCurrency(product.spend)], ["Revenue", fmtCurrency(product.revenue)], ["ROAS", fmtRoas(product.roas)],
            ["Impressions", fmtCount(product.impressions)], ["CTR", fmtPct(product.ctr)], ["CPM", fmtCurrency(product.cpm)]]).map(([l, v]) => (
            <div key={l} className="card-inset p-3"><p className="muted text-[11px]">{l}</p><p className="font-bold mt-0.5">{v}</p></div>
          ))}
        </div>

        <h3 className="text-[13px] font-semibold mt-6 mb-1">Daily spend</h3>
        {trend.data
          ? <Chart height={210} option={areaOption(trend.data.trend.map((t) => ({ label: fmtShortDate(t.date), value: t.spend })), fmtCurrency)} />
          : <Skeleton className="h-52" />}

        <div className="flex items-center justify-between mt-6 mb-2">
          <h3 className="text-[13px] font-semibold">Where the spend went</h3>
          <div className="flex gap-1.5">
            {(["campaign", "adset", "ad"] as const).map((b) => (
              <button key={b} className="pill" data-active={by === b} onClick={() => setBy(b)}>{b}</button>
            ))}
          </div>
        </div>
        <table className="w-full">
          <thead><tr><th className="th !text-left">Name</th><th className="th">Spend</th><th className="th">ROAS</th></tr></thead>
          <tbody>
            {bd.data?.breakdown.map((r) => (
              <tr key={r.name}><td className="td !text-left">{r.name}</td><td className="td">{fmtCurrency(r.spend)}</td><td className="td">{fmtRoas(r.roas)}</td></tr>
            ))}
          </tbody>
        </table>
      </aside>
    </div>
  );
}
