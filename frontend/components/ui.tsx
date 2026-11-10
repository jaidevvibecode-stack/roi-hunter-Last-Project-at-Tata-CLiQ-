"use client";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import type { ReactNode } from "react";
import { fmtDelta } from "@/lib/formatters";

export function DeltaBadge({ value, invert = false }: { value: number | null | undefined; invert?: boolean }) {
  if (value === null || value === undefined) return <span className="muted text-xs">—</span>;
  const good = invert ? value < 0 : value > 0;
  const Icon = value >= 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={`inline-flex items-center gap-0.5 text-xs font-semibold ${good ? "up" : "down"}`}>
      <Icon size={13} />
      {fmtDelta(value)}
    </span>
  );
}

export function SegmentTag({ segment }: { segment?: string }) {
  if (!segment) return null;
  const cls = segment.split(" ")[0];
  return (
    <span className={`seg-${cls} text-[10.5px] font-semibold px-2 py-0.5 rounded-full`}>{segment}</span>
  );
}

export function PageTitle({ title, sub, right }: { title: string; sub?: string; right?: ReactNode }) {
  return (
    <div className="flex items-end justify-between mb-5 px-1">
      <div>
        <h1 className="text-[22px] font-bold tracking-tight">{title}</h1>
        {sub && <p className="muted text-[13px] mt-1">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

export function Skeleton({ className = "h-24" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="card p-6 text-sm">
      <p className="font-semibold down mb-1">Could not load data</p>
      <p className="muted">
        {String((error as Error)?.message ?? error)} — is the backend running on port 8000?
      </p>
    </div>
  );
}

export function Card({ children, className = "", title, action }: {
  children: ReactNode; className?: string; title?: string; action?: ReactNode;
}) {
  return (
    <section className={`card p-5 ${className}`}>
      {(title || action) && (
        <div className="flex items-center justify-between mb-3">
          {title && <h2 className="text-[13px] font-semibold">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
