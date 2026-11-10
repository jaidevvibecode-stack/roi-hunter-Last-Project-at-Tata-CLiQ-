"use client";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Clock, XCircle, AlertTriangle } from "lucide-react";
import { api, type DataQualityResponse, type FreshnessResponse } from "@/lib/api";
import { fmtCurrency } from "@/lib/formatters";
import { Chart } from "@/components/charts";
import { Card, ErrorBox, PageTitle, Skeleton } from "@/components/ui";


const ICON: Record<string, React.ReactNode> = {
  ok: <CheckCircle2 size={15} className="up" />, warn: <AlertTriangle size={15} style={{ color: "var(--warn)" }} />,
  error: <XCircle size={15} className="down" />, pending: <Clock size={15} className="muted" />,
};

export default function DataHealthPage() {
  const dq = useQuery({ queryKey: ["dq"], queryFn: () => api<DataQualityResponse>("api/v1/data-quality") });
  const fr = useQuery({ queryKey: ["fresh"], queryFn: () => api<FreshnessResponse>("api/v1/meta/freshness") });
  if (dq.error) return <ErrorBox error={dq.error} />;
  const demo = dq.data?.meta.data_source === "demo";

  return (
    <div className="fade-in">
      <PageTitle title="Data health" sub="Freshness, reconciliation and quality checks — the trust layer behind every number" />
      {demo && (
        <div className="card p-4 mb-3 text-[13px]" style={{ borderColor: "rgba(251,191,36,.3)" }}>
          <b style={{ color: "var(--warn)" }}>Integration pending.</b>{" "}
          <span className="muted">
            Checks below show <b>pending</b> because Meta, Mixpanel and Redshift are not connected yet. The reconciliation chart is synthetic.
          </span>
        </div>
      )}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 mb-3">
        {fr.data?.sources.map((s) => (
          <Card key={s.source}>
            <div className="flex items-center gap-2">{ICON[s.status] ?? ICON.pending}<p className="text-[13px] font-semibold">{s.source}</p></div>
            <p className="muted text-[11px] mt-2">Last run: {s.last_run_at ?? "—"}</p>
            <p className="muted text-[11px]">Latest data: {s.latest_data_date ?? "—"}</p>
          </Card>
        ))}
      </div>
      <div className="grid grid-cols-12 gap-3">
        <Card className="col-span-12 xl:col-span-7" title="Spend reconciliation — ad-level vs product-level">
          {!dq.data ? <Skeleton className="h-72" /> : (
            <Chart height={290} option={{
              grid: { left: 8, right: 8, top: 24, bottom: 8, containLabel: true },
              legend: { top: 0, right: 0, textStyle: { color: "#8b8b92", fontSize: 11 }, icon: "circle" },
              tooltip: { trigger: "axis", backgroundColor: "#1a1a1d", borderColor: "rgba(255,255,255,.12)", textStyle: { color: "#fff", fontSize: 12 } },
              xAxis: { type: "category", data: [...dq.data.reconciliation].reverse().map((r) => r.report_date.slice(5)), axisLabel: { color: "#6b6b73", fontSize: 10 }, axisLine: { show: false }, axisTick: { show: false } },
              yAxis: { type: "value", axisLabel: { color: "#6b6b73", fontSize: 10, formatter: (v: number) => fmtCurrency(v) }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } },
              series: [
                { name: "Product-level", type: "bar", stack: "s", data: [...dq.data.reconciliation].reverse().map((r) => r.product_level_spend), itemStyle: { color: "rgba(255,255,255,.28)" } },
                { name: "Unallocated", type: "bar", stack: "s", data: [...dq.data.reconciliation].reverse().map((r) => r.unallocated_spend), itemStyle: { color: "#f43f5e" } },
              ],
            }} />
          )}
        </Card>
        <Card className="col-span-12 xl:col-span-5" title="Quality checks">
          {dq.data?.checks.map((c) => (
            <div key={c.check_name} className="flex items-center gap-3 py-2.5 border-t first:border-t-0" style={{ borderColor: "var(--border)" }}>
              {ICON[c.status] ?? ICON.pending}
              <div className="flex-1">
                <p className="text-[13px] font-medium">{c.check_name.replaceAll("_", " ")}</p>
                <p className="muted text-[11px]">{String(c.details?.note ?? (c.observed !== null ? `observed ${c.observed}` : ""))}</p>
              </div>
              <span className="muted text-[11px] uppercase">{c.status}</span>
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
}
