"use client";
import dynamic from "next/dynamic";
import type { EChartsOption } from "echarts";

const ReactECharts = dynamic(() => import("echarts-for-react"), {
  ssr: false,
  loading: () => <div className="skeleton h-full w-full" />,
});

const AXIS = { color: "#6b6b73", fontSize: 11, fontFamily: "inherit" };

export function Chart({ option, height = 300 }: { option: EChartsOption; height?: number }) {
  return <ReactECharts option={option} style={{ height, width: "100%" }} notMerge lazyUpdate />;
}

/** White smooth line with soft gradient fill and a pill tooltip — mirrors the reference dashboard. */
export function areaOption(
  points: { label: string; value: number | null }[],
  fmt: (v: number) => string
): EChartsOption {
  return {
    animationDuration: 600,
    grid: { left: 8, right: 16, top: 24, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "axis",
      backgroundColor: "#1a1a1d",
      borderColor: "rgba(255,255,255,.12)",
      textStyle: { color: "#fff", fontSize: 12, fontWeight: 600 },
      padding: [6, 12],
      extraCssText: "border-radius:999px;box-shadow:none;",
      axisPointer: { type: "line", lineStyle: { color: "rgba(255,255,255,.25)", type: "dashed" } },
      formatter: (p: unknown) => {
        const a = (p as { name: string; value: number }[])[0];
        return `<span style="color:#9a9aa2;font-weight:500">${a.name}</span>&nbsp;&nbsp;${fmt(a.value)}`;
      },
    },
    xAxis: {
      type: "category", data: points.map((p) => p.label), boundaryGap: false,
      axisLine: { show: false }, axisTick: { show: false }, axisLabel: { ...AXIS, interval: "auto" },
    },
    yAxis: {
      type: "value", axisLabel: { ...AXIS, formatter: (v: number) => fmt(v) },
      splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } }, axisLine: { show: false },
    },
    series: [{
      type: "line", smooth: 0.35, showSymbol: false, data: points.map((p) => p.value),
      lineStyle: { color: "#fff", width: 2.2 },
      emphasis: { focus: "series" },
      itemStyle: { color: "#fff", borderColor: "#fff", borderWidth: 3 },
      areaStyle: {
        color: { type: "linear", x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: "rgba(255,255,255,.22)" }, { offset: 1, color: "rgba(255,255,255,0)" }] },
      },
    }],
  };
}
