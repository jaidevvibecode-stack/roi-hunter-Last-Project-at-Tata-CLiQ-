import type { Metadata } from "next";
import { Manrope } from "next/font/google";
import { Suspense } from "react";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { Sidebar } from "@/components/Sidebar";
import { TopBar } from "@/components/TopBar";

export const dynamic = "force-dynamic";

const manrope = Manrope({ subsets: ["latin"], weight: ["400", "500", "600", "700", "800"] });

export const metadata: Metadata = {
  title: "ROI Hunter — SKU Ad Performance",
  description: "SKU-level Meta advertising analytics: spend, ROAS, CPM, CTR per product.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${manrope.className} antialiased`}>
        <Providers>
          <div className="flex h-screen overflow-hidden p-3 gap-3">
            <Sidebar />
            <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
              <Suspense fallback={<div style={{ height: 56 }} />}>
                <TopBar />
              </Suspense>
              <main className="flex-1 overflow-auto px-2 pb-6">
                <Suspense fallback={<div className="skeleton h-96" />}>{children}</Suspense>
              </main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
