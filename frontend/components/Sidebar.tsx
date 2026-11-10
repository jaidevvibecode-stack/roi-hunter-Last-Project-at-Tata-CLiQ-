"use client";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Activity, BarChart3, ChevronRight, Layers, Lightbulb, ShieldCheck, ShoppingBag, TrendingUp } from "lucide-react";

const NAV = [
  { href: "/overview", label: "Overview", icon: BarChart3 },
  { href: "/products", label: "Products", icon: ShoppingBag },
  { href: "/segments", label: "Segments", icon: Layers },
  { href: "/recommendations", label: "Recommendations", icon: Lightbulb },
  { href: "/trends", label: "Trends", icon: TrendingUp },
  { href: "/attribution", label: "Attribution", icon: Activity },
  { href: "/data-health", label: "Data Health", icon: ShieldCheck },
];

export function Sidebar() {
  const pathname = usePathname();
  const qs = useSearchParams().toString(); // keep global filters when navigating

  return (
    <aside className="card w-60 flex-shrink-0 flex flex-col py-5 px-3">
      <div className="flex items-center gap-2.5 px-3 pb-6">
        <div className="w-7 h-7 rounded-full bg-white flex items-center justify-center">
          <div className="w-3 h-3 rounded-full bg-black" />
        </div>
        <span className="text-[11px] font-extrabold tracking-[0.18em]">ROI HUNTER</span>
      </div>

      <nav className="flex-1 space-y-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={qs ? `${href}?${qs}` : href}
              className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-[13px] transition-colors relative"
              style={{
                color: active ? "#fff" : "var(--muted)",
                background: active ? "rgba(255,255,255,0.06)" : "transparent",
              }}
            >
              {active && <span className="absolute left-0 top-2 bottom-2 w-[2px] rounded bg-white" />}
              <Icon size={15} strokeWidth={1.8} />
              <span className="flex-1 font-medium">{label}</span>
              <ChevronRight size={13} style={{ opacity: active ? 0.9 : 0.35 }} />
            </Link>
          );
        })}
      </nav>

      <div className="card-inset p-3.5 text-[11px] leading-relaxed">
        <p className="font-semibold text-white mb-1">Phase 1 · Meta catalog ads</p>
        <p className="muted">
          Product-level spend, CPM, CTR and ROAS. Revenue comes from first-party data
          (Mixpanel / Redshift) — Meta does not report it per product.
        </p>
      </div>
    </aside>
  );
}
