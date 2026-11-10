"use client";
import { useSearchParams } from "next/navigation";
import { ProductsTable } from "@/components/ProductsTable";
import { PageTitle } from "@/components/ui";

export default function ProductsPage() {
  const q = useSearchParams().get("q") ?? "";
  return (
    <div className="fade-in">
      <PageTitle title="Products" sub="SKU-level performance — spend, impressions, CPM, CTR, ROAS per catalog product" />
      <ProductsTable key={q} initialQuery={q} />
    </div>
  );
}
