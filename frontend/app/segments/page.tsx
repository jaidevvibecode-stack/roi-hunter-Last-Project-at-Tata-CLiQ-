"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, filterQuery, useGlobalFilters, type SegmentsResponse } from "@/lib/api";
import { fmtCount, fmtCurrency, fmtPct, fmtRoas } from "@/lib/formatters";
import { Chart } from "@/components/charts";
import { Card, ErrorBox, PageTitle, SegmentTag, Skeleton } from "@/components/ui";

const COLORS: Record<string, string> = {
  Stars: "#34d399", "Hidden Gems": "#60a5fa", Bleeders: "#f43f5e", Zombies: "#71717a", "Insufficient data": "#3f3f46",
};
const BLURB: Record<string, string> = {
  Stars: "High spend, ROAS above target — protect and scale",
  "Hidden Gems": "ROAS above target but under-funded — test more budget",
  Bleeders: "High spend, ROAS below target — review or exclude",
  Zombies: "Low spend and low return — prune from catalog ads",
  "Insufficient data": "Below the minimum spend to classify",
};

export default function SegmentsPage() {
  const f = useGlobalFilters();
  const [active, setActive] = useState("Stars");
  const { data, error } = useQuery({
    queryKey: ["segments", f],
    queryFn: () => api<SegmentsResponse>("api/v1/segments", filterQuery(f)),
  });
  if (error) return <ErrorBox error={error} />;

  const list = (data?.products ?? []).filter((p) => p.segment === active).sort((a, b) => b.spend - a.spend).slice(0, 12);

  return (
    <div className="fade-in">
      <PageTitle title="Product segments" sub="Quadrants of spend vs ROAS — thresholds are configurable in config/segments.yml" />
      {!data ? <Skeleton className="h-[500px]" /> : (
        <div className="grid grid-cols-12 gap-3">
          <div className="col-span-12 grid grid-cols-2 md:grid-cols-5 gap-3">
            {data.summary.map((s) => (
              <button key={s.segment} onClick={() => setActive(s.segment)} className="card p-4 text-left"
                style={active === s.segment ? { borderColor: "rgba(255,255,255,.4)" } : {}}>
                <SegmentTag segment={s.segment} />
                <p className="text-xl font-bold mt-2">{s.products}</p>
                <p className="muted text-[11px]">{fmtCurrency(s.spend)} · {fmtRoas(s.roas)}</p>
              </button>
            ))}
          </div>

          <Card className="col-span-12 xl:col-span-7" title="Spend vs ROAS (each dot is a SKU)">
            <Chart height={400} option={{
              grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
              tooltip: {
                backgroundColor: "#1a1a1d", borderColor: "rgba(255,255,255,.12)", textStyle: { color: "#fff", fontSize: 12 },
                formatter: (p: unknown) => {
                  const d = (p as { data: [number, number, string, string] }).data;
                  return `<b>${d[2]}</b><br/>Spend ${fmtCurrency(d[0])} · ROAS ${fmtRoas(d[1])}<br/><span style="color:#8b8b92">${d[3]}</span>`;
                },
              },
              xAxis: { type: "log", name: "Spend", nameTextStyle: { color: "#6b6b73" }, axisLabel: { color: "#6b6b73", fontSize: 10, formatter: (v: number) => fmtCurrency(v) }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } },
              yAxis: { type: "value", name: "ROAS", nameTextStyle: { color: "#6b6b73" }, axisLabel: { color: "#6b6b73", fontSize: 10, formatter: (v: number) => `${v}x` }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } },
              series: Object.keys(COLORS).map((seg) => ({
                name: seg, type: "scatter" as const, symbolSize: 7,
                itemStyle: { color: COLORS[seg], opacity: 0.85 },
                data: data.products.filter((p) => p.segment === seg && p.spend > 0 && p.roas !== null)
                  .map((p) => [p.spend, p.roas, p.product_name, seg]),
              })),
            }} />
          </Card>

          <Card className="col-span-12 xl:col-span-5" title={active}>
            <p className="muted text-xs mb-3">{BLURB[active]}</p>
            <table className="w-full">
              <thead><tr><th className="th !text-left">Product</th><th className="th">Spend</th><th className="th">ROAS</th><th className="th">Orders</th></tr></thead>
              <tbody>
                {list.map((p) => (
                  <tr key={p.product_key}>
                    <td className="td !text-left"><b>{p.product_name}</b></td>
                    <td className="td">{fmtCurrency(p.spend)}</td>
                    <td className="td">{fmtRoas(p.roas)}</td>
                    <td className="td">{fmtCount(p.orders)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted text-[11px] mt-3">
              Spend share of segment: {fmtPct(data.summary.find((s) => s.segment === active)?.spend_share ?? null, 1)}
            </p>
          </Card>
        </div>
      )}
    </div>
  );
}
