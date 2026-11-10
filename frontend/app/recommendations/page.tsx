"use client";
import { useQuery } from "@tanstack/react-query";
import { Download, ShieldCheck } from "lucide-react";
import { api, filterQuery, useGlobalFilters, type Recommendation, type RecommendationsResponse } from "@/lib/api";
import { fmtCurrency, fmtRoas } from "@/lib/formatters";
import { Card, ErrorBox, PageTitle, Skeleton } from "@/components/ui";

const SEV: Record<string, { label: string; color: string }> = {
  critical: { label: "Needs action", color: "#f43f5e" },
  opportunity: { label: "Opportunity", color: "#34d399" },
  info: { label: "Info", color: "#a1a1aa" },
};

function downloadSkus(rec: Recommendation) {
  const blob = new Blob(["retailer_id\n" + rec.retailer_ids.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${rec.rule_id}_skus.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

export default function RecommendationsPage() {
  const f = useGlobalFilters();
  const { data, error } = useQuery({
    queryKey: ["recs", f],
    queryFn: () => api<RecommendationsResponse>("api/v1/recommendations", filterQuery(f)),
  });
  if (error) return <ErrorBox error={error} />;

  return (
    <div className="fade-in">
      <PageTitle title="Recommendations" sub="Rule-based suggestions from product segments and stock status"
        right={<span className="pill"><ShieldCheck size={12} /> Recommendation-only — nothing is changed in Meta</span>} />
      {!data ? <Skeleton className="h-96" /> : (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
          {data.recommendations.map((r) => (
            <Card key={r.rule_id}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <span className="text-[10.5px] font-bold tracking-wide px-2 py-0.5 rounded-full"
                    style={{ color: SEV[r.severity].color, background: SEV[r.severity].color + "1a" }}>
                    {SEV[r.severity].label.toUpperCase()}
                  </span>
                  <h3 className="font-bold text-[15px] mt-2">{r.action}</h3>
                  <p className="muted text-xs mt-1">{r.reason}</p>
                </div>
                <button className="btn-light flex-shrink-0" onClick={() => downloadSkus(r)}>
                  <Download size={12} /> {r.product_count} SKUs
                </button>
              </div>
              <div className="grid grid-cols-2 gap-2 mt-4">
                <div className="card-inset p-3"><p className="muted text-[11px]">Spend affected</p><p className="font-bold">{fmtCurrency(r.spend_affected)}</p></div>
                <div className="card-inset p-3"><p className="muted text-[11px]">Revenue affected</p><p className="font-bold">{fmtCurrency(r.revenue_affected)}</p></div>
              </div>
              <table className="w-full mt-2">
                <tbody>
                  {r.top_products.map((p) => (
                    <tr key={p.product_key}>
                      <td className="td !text-left">{p.product_name}</td>
                      <td className="td">{fmtCurrency(p.spend)}</td>
                      <td className="td">{fmtRoas(p.roas)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
