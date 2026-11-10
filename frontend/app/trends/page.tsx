"use client";
import { useQuery } from "@tanstack/react-query";
import { api, filterQuery, useGlobalFilters, type TrendsResponse } from "@/lib/api";
import { fmtCurrency, fmtRoas, fmtShortDate } from "@/lib/formatters";
import { Chart } from "@/components/charts";
import { Card, ErrorBox, PageTitle, Skeleton } from "@/components/ui";

export default function TrendsPage() {
  const f = useGlobalFilters();
  const { data, error } = useQuery({
    queryKey: ["trends", f],
    queryFn: () => api<TrendsResponse>("api/v1/trends", filterQuery(f)),
  });
  if (error) return <ErrorBox error={error} />;
  const s = data?.series ?? [];
  const axis = { color: "#6b6b73", fontSize: 11 };

  return (
    <div className="fade-in">
      <PageTitle title="Trends" sub="Daily spend vs attributed revenue, with ROAS" />
      <Card>
        {!data ? <Skeleton className="h-[430px]" /> : (
          <Chart height={430} option={{
            grid: { left: 8, right: 8, top: 40, bottom: 8, containLabel: true },
            legend: { top: 0, right: 0, textStyle: { color: "#8b8b92", fontSize: 11 }, icon: "circle" },
            tooltip: { trigger: "axis", backgroundColor: "#1a1a1d", borderColor: "rgba(255,255,255,.12)", textStyle: { color: "#fff", fontSize: 12 } },
            xAxis: { type: "category", data: s.map((p) => fmtShortDate(p.date)), axisLine: { show: false }, axisTick: { show: false }, axisLabel: axis },
            yAxis: [
              { type: "value", axisLabel: { ...axis, formatter: (v: number) => fmtCurrency(v) }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } },
              { type: "value", axisLabel: { ...axis, formatter: (v: number) => fmtRoas(v) }, splitLine: { show: false } },
            ],
            series: [
              { name: "Spend", type: "bar", data: s.map((p) => p.spend), itemStyle: { color: "rgba(255,255,255,.22)", borderRadius: [3, 3, 0, 0] } },
              { name: "Revenue", type: "line", smooth: 0.3, showSymbol: false, data: s.map((p) => p.revenue), lineStyle: { color: "#fff", width: 2.2 } },
              { name: "ROAS", type: "line", yAxisIndex: 1, smooth: 0.3, showSymbol: false, data: s.map((p) => p.roas), lineStyle: { color: "#34d399", width: 1.6, type: "dashed" } },
            ],
          }} />
        )}
      </Card>
    </div>
  );
}
