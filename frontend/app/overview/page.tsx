import type { Metadata } from "next";
import { OverviewDashboard } from "@/components/OverviewDashboard";

export const metadata: Metadata = {
  title: "Overview — ROI Hunter",
  description: "KPI totals: Spend, Impressions, CTR, CPM, ROAS, Revenue across all products.",
};

export default function OverviewPage() {
  return <OverviewDashboard />;
}
