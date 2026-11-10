"use client";
import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Search } from "lucide-react";
import { api, filterQuery, useGlobalFilters, type Overview } from "@/lib/api";
import { fmtCount, fmtCurrency, fmtPct, fmtRoas, fmtShortDate } from "@/lib/formatters";
import { Chart, areaOption } from "./charts";
import { Card, DeltaBadge, ErrorBox, PageTitle, Skeleton } from "./ui";

type HeroKey = "spend" | "revenue" | "roas";
const HERO: Record<HeroKey, { label: string; fmt: (v: number) => string }> = {
  spend: { label: "Ad spend", fmt: (v) => fmtCurrency(v) },
  revenue: { label: "Attributed revenue", fmt: (v) => fmtCurrency(v) },
  roas: { label: "ROAS", fmt: (v) => fmtRoas(v) },
};

export function OverviewDashboard() {
  const f = useGlobalFilters();
  const [hero, setHero] = useState<HeroKey>("spend");
  const [q, setQ] = useState("");

  const { data, error, isLoading } = useQuery({
    queryKey: ["overview", f],
    queryFn: () => api<Overview>("api/v1/overview", filterQuery(f)),
  });

  const points = useMemo(
    () => (data?.trend ?? []).map((t) => ({ label: fmtShortDate(t.date), value: t[hero] })),
    [data, hero]
  );

  if (error) return <ErrorBox error={error} />;
  if (isLoading || !data) {
    return (
      <div className="grid grid-cols-12 gap-3">
        <Skeleton className="col-span-8 h-[420px]" /><Skeleton className="col-span-4 h-[420px]" />
        <Skeleton className="col-span-12 h-56" />
      </div>
    );
  }

  const k = data.kpis;
  const heroMetric = k[hero];
  const rows = data.top_products_by_spend.filter((p) =>
    (p.product_name + p.retailer_id).toLowerCase().includes(q.toLowerCase())
  );
  const stars = data.segment_summary.find((s) => s.segment === "Stars");
  const bleeders = data.segment_summary.find((s) => s.segment === "Bleeders");

  return (
    <div className="fade-in">
      <PageTitle title="Overview" sub={`${data.period.start} → ${data.period.end} · ${data.meta.attribution_model} · ${data.meta.lookback_days}-day click`} />

      <div className="grid grid-cols-12 gap-3">
        {/* Hero chart */}
        <Card className="col-span-12 xl:col-span-8">
          <div className="flex items-start justify-between">
            <div>
              <p className="muted text-xs">{HERO[hero].label}</p>
              <p className="text-[34px] font-extrabold tracking-tight leading-tight mt-1">
                {heroMetric.value === null ? "—" : HERO[hero].fmt(heroMetric.value)}
              </p>
              <p className="text-xs mt-1 flex items-center gap-2">
                <DeltaBadge value={heroMetric.delta_pct} />
                <span className="muted">vs previous period</span>
              </p>
            </div>
            <div className="flex gap-1.5">
              {(Object.keys(HERO) as HeroKey[]).map((h) => (
                <button key={h} className="pill" data-active={hero === h} onClick={() => setHero(h)}>
                  {HERO[h].label.split(" ").pop()}
                </button>
              ))}
            </div>
          </div>
          <Chart option={areaOption(points, HERO[hero].fmt)} height={310} />
        </Card>

        {/* Right column */}
        <div className="col-span-12 xl:col-span-4 flex flex-col gap-3">
          <Card>
            <p className="muted text-xs">Blended ROAS</p>
            <p className="text-2xl font-extrabold mt-1">{fmtRoas(k.roas.value)}</p>
            <div className="flex items-center justify-between mt-2">
              <DeltaBadge value={k.roas.delta_pct} />
              <Link href="/products" className="pill">See more</Link>
            </div>
            <div className="card-inset mt-4 p-3 text-[11.5px] muted leading-relaxed space-y-1">
              <p title="Meta's own product-level split does not add up to ad-level spend">
                Unallocated spend (Meta estimate gap): <b className="text-white">{fmtCurrency(data.unallocated_spend)}</b>
              </p>
              <p title="Spend on product ids that are not in the catalog: excluded from the product table">
                Unmapped spend (id not in catalog): <b className="text-white">{fmtCurrency(data.unmapped_spend)}</b>
              </p>
            </div>
          </Card>
          <Card className="flex-1">
            <h3 className="font-bold text-[15px]">Product segments</h3>
            <p className="muted text-xs mt-1 leading-relaxed">
              {stars ? `${stars.products} Stars drive ${fmtPct(stars.spend_share, 0)} of spend at ${fmtRoas(stars.roas)}. ` : ""}
              {bleeders ? `${bleeders.products} Bleeders burn ${fmtCurrency(bleeders.spend)} below target ROAS.` : ""}
            </p>
            <div className="flex gap-2 mt-4">
              <Link href="/segments" className="btn-light">Explore segments <ArrowRight size={12} /></Link>
              <Link href="/recommendations" className="btn-light">Actions</Link>
            </div>
          </Card>
        </div>

        {/* KPI strip */}
        <div className="col-span-12 grid grid-cols-2 md:grid-cols-5 gap-3">
        {([
          ["Impressions", fmtCount(k.impressions.value), k.impressions.delta_pct, false],
          ["CPM", fmtCurrency(k.cpm.value), k.cpm.delta_pct, true],
          ["Link CTR", fmtPct(k.ctr.value), k.ctr.delta_pct, false],
          ["CPC", fmtCurrency(k.cpc.value), k.cpc.delta_pct, true],
          ["Orders", fmtCount(k.orders.value), k.orders.delta_pct, false],
        ] as const).map(([label, value, delta, invert]) => (
          <Card key={label}>
            <p className="muted text-xs">{label}</p>
            <p className="text-xl font-bold mt-1">{value}</p>
            <div className="mt-1"><DeltaBadge value={delta} invert={invert} /></div>
          </Card>
        ))}
        </div>

        {/* Table + Pareto */}
        <Card className="col-span-12 xl:col-span-8" title="Top products by spend"
          action={
            <label className="card-inset flex items-center gap-2 px-3 py-1.5 w-56">
              <Search size={13} className="muted" />
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search products"
                className="bg-transparent outline-none text-xs w-full placeholder:text-[#55555c]" />
            </label>
          }>
          <div className="overflow-x-auto -mx-2">
            <table className="w-full">
              <thead>
                <tr>
                  <th className="th !text-left">Product</th><th className="th">Spend</th><th className="th">ROAS</th><th className="th">CTR</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.product_key} className="tr-hover">
                    <td className="td !text-left">
                      <Link href={`/products?q=${encodeURIComponent(p.retailer_id)}`} className="block">
                        <span className="font-semibold">{p.product_name}</span>
                        <span className="muted text-[11px] ml-2">{p.retailer_id}</span>
                      </Link>
                    </td>
                    <td className="td font-semibold">{fmtCurrency(p.spend)}</td>
                    <td className={`td font-semibold ${(p.roas ?? 0) >= 3 ? "up" : "down"}`}>{fmtRoas(p.roas)}</td>
                    <td className="td">{fmtPct(p.ctr)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="col-span-12 xl:col-span-4" title="Spend concentration">
          <p className="muted text-xs mb-2">
            {data.pareto_spend.skus_for_80pct} SKUs ({fmtPct(data.pareto_spend.share_of_skus_for_80pct, 0)} of catalog) drive 80% of spend.
          </p>
          <Chart height={230} option={{
            grid: { left: 8, right: 12, top: 10, bottom: 8, containLabel: true },
            xAxis: { type: "value", min: 0, max: 1, axisLabel: { color: "#6b6b73", fontSize: 10, formatter: (v: number) => `${v * 100}%` }, splitLine: { show: false } },
            yAxis: { type: "value", min: 0, max: 1, axisLabel: { color: "#6b6b73", fontSize: 10, formatter: (v: number) => `${v * 100}%` }, splitLine: { lineStyle: { color: "rgba(255,255,255,.05)" } } },
            tooltip: { trigger: "axis", backgroundColor: "#1a1a1d", textStyle: { color: "#fff", fontSize: 11 }, borderColor: "rgba(255,255,255,.12)" },
            series: [{
              type: "line", smooth: true, showSymbol: false, lineStyle: { color: "#fff", width: 2 },
              areaStyle: { color: "rgba(255,255,255,.08)" },
              data: data.pareto_spend.curve.map((c) => [c.sku_pct, c.cum_share]),
            }],
          }} />
        </Card>
      </div>
    </div>
  );
}
