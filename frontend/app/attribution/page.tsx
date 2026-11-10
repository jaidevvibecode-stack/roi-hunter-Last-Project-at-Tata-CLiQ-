"use client";
import { useQuery } from "@tanstack/react-query";
import { api, filterQuery, useGlobalFilters, type AttributionCompareResponse, type AttributionRow } from "@/lib/api";
import { fmtCurrency, fmtRoas } from "@/lib/formatters";
import { Card, ErrorBox, PageTitle, Skeleton } from "@/components/ui";

const MODELS = [
  ["M1", "Same-SKU click", "Purchase of the SKU that was clicked (default)"],
  ["M2", "Halo", "Whole order credited to the clicked SKU"],
  ["M3", "Modelled", "Meta-reported value split by click share (proxy)"],
  ["M4", "Last paid touch", "Purchased SKU, Meta was last paid touch"],
] as const;

export default function AttributionPage() {
  const f = useGlobalFilters();
  const { data, error } = useQuery({
    queryKey: ["attr", f],
    queryFn: () => api<AttributionCompareResponse>("api/v1/attribution/compare", filterQuery(f, { page_size: 30 })),
  });
  if (error) return <ErrorBox error={error} />;
  const best = (r: AttributionRow) => Math.max(...[r.roas_m1, r.roas_m2, r.roas_m3, r.roas_m4].map((v) => v ?? -1));

  return (
    <div className="fade-in">
      <PageTitle title="Attribution comparison" sub="Same product, four ways of crediting revenue — pick the model that matches how you judge ads" />
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 mb-3">
        {MODELS.map(([k, n, d]) => (
          <Card key={k}><p className="text-xs font-bold">{k} · {n}</p><p className="muted text-[11.5px] mt-1 leading-relaxed">{d}</p></Card>
        ))}
      </div>
      <Card title="Top products by spend">
        {!data ? <Skeleton className="h-96" /> : (
          <table className="w-full">
            <thead><tr>
              <th className="th !text-left">Product</th><th className="th">Spend</th>
              {MODELS.map(([k]) => <th key={k} className="th">{k} ROAS</th>)}
            </tr></thead>
            <tbody>
              {data.data.map((r) => (
                <tr key={r.product_key}>
                  <td className="td !text-left"><b>{r.product_name}</b> <span className="muted text-[11px] ml-1">{r.retailer_id}</span></td>
                  <td className="td">{fmtCurrency(r.spend)}</td>
                  {([r.roas_m1, r.roas_m2, r.roas_m3, r.roas_m4]).map((v, i) => (
                    <td key={i} className={`td ${v !== null && v === best(r) ? "font-bold up" : ""}`}>{fmtRoas(v)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
