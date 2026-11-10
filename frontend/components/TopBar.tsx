"use client";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { FlaskConical } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { api, useGlobalFilters, type Meta } from "@/lib/api";

const MODELS: Record<string, string> = {
  M1: "M1 · Same-SKU click",
  M2: "M2 · Halo (whole order)",
  M3: "M3 · Modelled",
  M4: "M4 · Last paid touch",
};

export function TopBar() {
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();
  const f = useGlobalFilters();

  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: () => api<{ data_source: Meta["data_source"] }>("health"),
    staleTime: 5 * 60_000,
  });

  // Rapid successive changes (e.g. 7D then 28d) must not clobber each other: build on the latest *pending* URL,
  // not on the possibly stale params of the current render.
  const pending = useRef<string | null>(null);
  const current = sp.toString();
  useEffect(() => {
    if (pending.current === current) pending.current = null;
  }, [current]);

  const set = (k: string, v: string) => {
    const p = new URLSearchParams(pending.current ?? current);
    p.set(k, v);
    pending.current = p.toString();
    router.push(`${pathname}?${pending.current}`, { scroll: false });
  };

  return (
    <header className="flex items-center gap-3 px-2 h-14 flex-shrink-0">
      {health?.data_source === "demo" && (
        <span
          className="inline-flex items-center gap-1.5 text-[11px] font-bold tracking-wide px-3 py-1.5 rounded-full"
          style={{ background: "rgba(251,191,36,.12)", color: "var(--warn)", border: "1px solid rgba(251,191,36,.3)" }}
          title="All figures on screen are synthetic. Real Meta / Mixpanel / Redshift integration is pending access."
        >
          <FlaskConical size={12} /> DEMO DATA · SYNTHETIC
        </span>
      )}

      <div className="ml-auto flex items-center gap-2">
        {(["7", "30", "90"] as const).map((r) => (
          <button key={r} className="pill" data-active={f.range === r} onClick={() => set("range", r)}>
            {r}D
          </button>
        ))}
        <select
          aria-label="Attribution model"
          value={f.model}
          onChange={(e) => set("attribution_model", e.target.value)}
          className="pill appearance-none pr-4"
          style={{ background: "#0a0a0b", colorScheme: "dark" }}
        >
          {Object.entries(MODELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        {/* Only the window the marts actually compute is offered (API refuses others instead of faking them). */}
        <span className="pill" data-active="true" title="Revenue is attributed within 7 days of the ad click. Other windows need the marts extended.">
          7d click
        </span>
      </div>
    </header>
  );
}
