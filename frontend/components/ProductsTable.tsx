"use client";
import { useEffect, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download, Search } from "lucide-react";
import { api, exportUrl, filterQuery, useGlobalFilters, type Product, type ProductsResponse } from "@/lib/api";
import { fmtCount, fmtCurrency, fmtPct, fmtRoas } from "@/lib/formatters";
import { Card, ErrorBox, Skeleton } from "./ui";
import { ProductDrawer } from "./ProductDrawer";

const COLS: { key: string; label: string; render: (p: Product) => React.ReactNode; sortable?: boolean }[] = [
  { key: "spend", label: "Spend", render: (p) => fmtCurrency(p.spend), sortable: true },
  { key: "cpm", label: "CPM", render: (p) => fmtCurrency(p.cpm), sortable: true },
  { key: "impressions", label: "Impressions", render: (p) => fmtCount(p.impressions), sortable: true },
  { key: "link_clicks", label: "Link clicks", render: (p) => fmtCount(p.link_clicks), sortable: true },
  { key: "ctr", label: "CTR", render: (p) => fmtPct(p.ctr), sortable: true },
  { key: "cpc", label: "CPC", render: (p) => fmtCurrency(p.cpc), sortable: true },
  { key: "orders", label: "Orders", render: (p) => fmtCount(p.orders), sortable: true },
  { key: "revenue", label: "Revenue", render: (p) => fmtCurrency(p.revenue), sortable: true },
  {
    key: "roas", label: "ROAS", sortable: true,
    render: (p) => <b className={(p.roas ?? 0) >= 3 ? "up" : "down"}>{fmtRoas(p.roas)}</b>,
  },
  { key: "spend_share", label: "Spend share", render: (p) => fmtPct(p.spend_share, 1), sortable: true },
];

export function ProductsTable({ initialQuery = "" }: { initialQuery?: string }) {
  const f = useGlobalFilters();
  const [sort, setSort] = useState("spend");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState(initialQuery);
  const [debounced, setDebounced] = useState(initialQuery);
  const [selected, setSelected] = useState<Product | null>(null);
  const pageSize = 25;

  useEffect(() => {
    const t = setTimeout(() => { setDebounced(search); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [search]);

  const { data, error, isLoading } = useQuery({
    queryKey: ["products", f, sort, order, page, debounced],
    queryFn: () =>
      api<ProductsResponse>("api/v1/products", filterQuery(f, { sort, order, page, page_size: pageSize, search: debounced })),
    placeholderData: keepPreviousData,
  });

  const toggle = (key: string) => {
    if (sort === key) setOrder(order === "desc" ? "asc" : "desc");
    else { setSort(key); setOrder("desc"); }
    setPage(1);
  };

  if (error) return <ErrorBox error={error} />;
  const pages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1;

  return (
    <Card>
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <label className="card-inset flex items-center gap-2 px-3 py-2 w-72">
          <Search size={14} className="muted" />
          <input value={search} onChange={(e) => setSearch(e.target.value)}
            placeholder="Search product name or SKU" maxLength={100}
            className="bg-transparent outline-none text-[13px] w-full placeholder:text-[#55555c]" />
        </label>
        <span className="pill" data-active="true" title="Every ROAS shows its attribution model">
          {f.model} · {f.lookback}d click
        </span>
        <span className="muted text-xs">{data ? `${data.total.toLocaleString("en-IN")} products` : ""}</span>
        <a className="btn-light ml-auto" href={exportUrl(f, sort)}><Download size={13} /> Export CSV</a>
      </div>

      {isLoading || !data ? <Skeleton className="h-96" /> : (
        <div className="overflow-x-auto -mx-2">
          <table className="w-full">
            <thead>
              <tr>
                <th className="th !text-left">Product</th>
                {COLS.map((c) => (
                  <th key={c.key} className="th cursor-pointer select-none hover:text-white" onClick={() => toggle(c.key)}>
                    <span className="inline-flex items-center gap-1">
                      {c.label}
                      {sort === c.key && (order === "desc" ? <ArrowDown size={11} /> : <ArrowUp size={11} />)}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.data.map((p) => (
                <tr key={p.product_key} className="tr-hover" onClick={() => setSelected(p)}>
                  <td className="td !text-left">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-lg card-inset flex items-center justify-center text-xs font-bold muted">
                        {p.product_name.slice(0, 1)}
                      </div>
                      <div>
                        <p className="font-semibold leading-tight">{p.product_name}</p>
                        <p className="muted text-[11px]">
                          {p.retailer_id} · {p.brand}
                          {p.availability === "out of stock" && <span className="down ml-2">out of stock</span>}
                        </p>
                      </div>
                    </div>
                  </td>
                  {COLS.map((c) => <td key={c.key} className="td">{c.render(p)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex items-center justify-end gap-2 mt-4">
        <span className="muted text-xs mr-2">Page {page} of {pages}</span>
        <button className="btn-light" disabled={page <= 1} onClick={() => setPage(page - 1)}><ChevronLeft size={13} /></button>
        <button className="btn-light" disabled={page >= pages} onClick={() => setPage(page + 1)}><ChevronRight size={13} /></button>
      </div>

      {selected && <ProductDrawer product={selected} onClose={() => setSelected(null)} />}
    </Card>
  );
}
