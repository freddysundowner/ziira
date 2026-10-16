import { useId, useRef, useState } from "react";

import { cx } from "@/sdk";

import { areaPath, type Box, describeSeries, donutSlices, linePath, nearestIndex, niceMax, ticks, xAt, yAt } from "../helpers/chart";

/** Colours for the parts of a donut, in order (design tokens only). */
export const PART_CLASSES = ["fill-brand", "fill-info", "fill-warn", "fill-ok", "fill-bad", "fill-muted"] as const;
export const PART_SWATCH = ["bg-brand", "bg-info", "bg-warn", "bg-ok", "bg-bad", "bg-muted"] as const;

interface SeriesProps {
  labels: string[];
  values: number[];
  /** How a value reads in the tooltip and for a screen reader ("KES 1,200.00", "12"). */
  format: (value: number) => string;
  /** What the chart shows, in a few words: becomes its accessible name. */
  label: string;
  empty?: string;
}

const VIEW: Box = { width: 640, height: 220, left: 8, right: 8, top: 12, bottom: 24 };

/**
 * A line (with a soft area under it) over a few buckets of time. Hovering or moving with the arrow keys shows the value;
 * a screen reader gets the whole series as text. Colours come from tokens; the draw-in has no animation to switch off.
 */
export function LineChart({ labels, values, format, label, empty }: SeriesProps) {
  const [active, setActive] = useState<number | null>(null);
  const gradient = useId();
  const svg = useRef<SVGSVGElement>(null);
  if (values.length === 0 || values.every((v) => v === 0)) {
    return <p className="flex h-[220px] items-center justify-center rounded-lg bg-sunken/50 text-sm text-muted">{empty}</p>;
  }
  const max = niceMax(Math.max(...values));
  const grid = ticks(max, 4);
  const move = (event: { clientX: number }) => {
    const rect = svg.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return;
    setActive(nearestIndex(((event.clientX - rect.left) / rect.width) * VIEW.width, values.length, VIEW));
  };
  const key = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowRight") setActive((a) => Math.min(values.length - 1, (a ?? -1) + 1));
    else if (e.key === "ArrowLeft") setActive((a) => Math.max(0, (a ?? values.length) - 1));
    else if (e.key === "Escape") setActive(null);
    else return;
    e.preventDefault();
  };
  const shown = active === null ? null : { x: xAt(active, values.length, VIEW), y: yAt(values[active] ?? 0, max, VIEW), label: labels[active] ?? "", value: format(values[active] ?? 0) };
  return (
    <div className="relative">
      <svg ref={svg} viewBox={`0 0 ${VIEW.width} ${VIEW.height}`} role="img" aria-label={`${label}. ${describeSeries(labels, values, format)}`} tabIndex={0}
        className="h-auto w-full rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand" onPointerMove={move} onPointerLeave={() => setActive(null)} onKeyDown={key} onBlur={() => setActive(null)}>
        <defs>
          <linearGradient id={gradient} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" style={{ stopColor: "rgb(var(--brand))" }} stopOpacity="0.28" />
            <stop offset="1" style={{ stopColor: "rgb(var(--brand))" }} stopOpacity="0" />
          </linearGradient>
        </defs>
        {grid.map((g) => (
          <line key={g} x1={VIEW.left} x2={VIEW.width - VIEW.right} y1={yAt(g, max, VIEW)} y2={yAt(g, max, VIEW)} className="stroke-line" strokeWidth="1" />
        ))}
        <path d={areaPath(values, max, VIEW)} fill={`url(#${gradient})`} />
        <path d={linePath(values, max, VIEW)} fill="none" className="stroke-brand" strokeWidth="2.25" strokeLinejoin="round" strokeLinecap="round" />
        {[0, Math.floor((labels.length - 1) / 2), labels.length - 1].map((i) => (
          <text key={i} x={xAt(i, labels.length, VIEW)} y={VIEW.height - 6} textAnchor={i === 0 ? "start" : i === labels.length - 1 ? "end" : "middle"} className="fill-muted text-[11px]">{labels[i]}</text>
        ))}
        {shown && (
          <>
            <line x1={shown.x} x2={shown.x} y1={VIEW.top} y2={VIEW.height - VIEW.bottom} className="stroke-muted" strokeDasharray="3 3" />
            <circle cx={shown.x} cy={shown.y} r="4.5" className="fill-surface stroke-brand" strokeWidth="2.25" />
          </>
        )}
      </svg>
      {shown && (
        <div className="pointer-events-none absolute top-1 rounded-lg border border-line bg-surface px-2 py-1 text-xs shadow-pop" style={{ left: `${Math.min(80, Math.max(0, (shown.x / VIEW.width) * 100 - 8))}%` }} role="status">
          <span className="text-muted">{shown.label}</span> <span className="tnum font-semibold">{shown.value}</span>
        </div>
      )}
    </div>
  );
}

/** Bars standing on a baseline: one per bucket, for counts such as new businesses. Keyboard and screen reader like the line chart. */
export function ColumnChart({ labels, values, format, label, empty }: SeriesProps) {
  const [active, setActive] = useState<number | null>(null);
  if (values.length === 0 || values.every((v) => v === 0)) {
    return <p className="flex h-[220px] items-center justify-center rounded-lg bg-sunken/50 text-sm text-muted">{empty}</p>;
  }
  const max = niceMax(Math.max(...values));
  const slot = (VIEW.width - VIEW.left - VIEW.right) / values.length;
  const key = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowRight") setActive((a) => Math.min(values.length - 1, (a ?? -1) + 1));
    else if (e.key === "ArrowLeft") setActive((a) => Math.max(0, (a ?? values.length) - 1));
    else if (e.key === "Escape") setActive(null);
    else return;
    e.preventDefault();
  };
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${VIEW.width} ${VIEW.height}`} role="img" aria-label={`${label}. ${describeSeries(labels, values, format)}`} tabIndex={0}
        className="h-auto w-full rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand" onPointerLeave={() => setActive(null)} onKeyDown={key} onBlur={() => setActive(null)}>
        {ticks(max, 4).map((g) => <line key={g} x1={VIEW.left} x2={VIEW.width - VIEW.right} y1={yAt(g, max, VIEW)} y2={yAt(g, max, VIEW)} className="stroke-line" strokeWidth="1" />)}
        {values.map((v, i) => {
          const top = yAt(v, max, VIEW);
          return (
            <rect key={labels[i] ?? i} x={VIEW.left + slot * i + slot * 0.15} width={slot * 0.7} y={top} height={Math.max(v > 0 ? 2 : 0, VIEW.height - VIEW.bottom - top)} rx="3"
              className={cx(active === i ? "fill-brand-strong" : "fill-brand")} onPointerEnter={() => setActive(i)} />
          );
        })}
        {[0, labels.length - 1].map((i) => <text key={i} x={VIEW.left + slot * i + slot / 2} y={VIEW.height - 6} textAnchor={i === 0 ? "start" : "end"} className="fill-muted text-[11px]">{labels[i]}</text>)}
      </svg>
      {active !== null && (
        <div className="pointer-events-none absolute top-1 rounded-lg border border-line bg-surface px-2 py-1 text-xs shadow-pop" style={{ left: `${Math.min(80, (active / values.length) * 100)}%` }} role="status">
          <span className="text-muted">{labels[active]}</span> <span className="tnum font-semibold">{format(values[active] ?? 0)}</span>
        </div>
      )}
    </div>
  );
}

/** A tiny line with no axes, for a figure card. Decorative unless given a label. */
export function Sparkline({ values, label, className }: { values: number[]; label?: string; className?: string }) {
  const box: Box = { width: 96, height: 28, left: 2, right: 2, top: 3, bottom: 3 };
  if (values.length < 2 || values.every((v) => v === 0)) return null;
  const max = Math.max(...values);
  return (
    <svg viewBox={`0 0 ${box.width} ${box.height}`} className={cx("h-7 w-24", className)} {...(label ? { role: "img", "aria-label": label } : { "aria-hidden": true })}>
      <path d={linePath(values, max, box)} fill="none" className="stroke-brand" strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

/** Shares of a whole as a ring with a legend (the legend carries the numbers, so the ring is never the only way to read them). */
export function Donut({ parts, label, empty, centre }: { parts: { key: string; label: string; value: number }[]; label: string; empty: string; centre?: string }) {
  const total = parts.reduce((n, p) => n + p.value, 0);
  if (total <= 0) return <p className="text-sm text-muted">{empty}</p>;
  const slices = donutSlices(parts.map((p) => p.value), 60, 38);
  return (
    <div className="flex flex-wrap items-center gap-4">
      <svg viewBox="0 0 120 120" className="h-28 w-28 shrink-0" role="img" aria-label={`${label}. ${parts.map((p) => `${p.label}: ${p.value}`).join(", ")}`}>
        {slices.map((s, i) => <path key={parts[i]?.key} d={s.path} className={cx(PART_CLASSES[i % PART_CLASSES.length], "stroke-surface")} strokeWidth="1.5" />)}
        {centre !== undefined && <text x="60" y="64" textAnchor="middle" className="fill-ink text-[18px] font-semibold">{centre}</text>}
      </svg>
      <ul className="min-w-0 flex-1 space-y-1 text-sm">
        {parts.map((p, i) => (
          <li key={p.key} className="flex items-center gap-2">
            <span className={cx("h-2.5 w-2.5 shrink-0 rounded-sm", PART_SWATCH[i % PART_SWATCH.length])} aria-hidden />
            <span className="truncate">{p.label}</span>
            <span className="tnum ml-auto text-muted">{p.value} <span className="text-xs">({Math.round((p.value / total) * 100)}%)</span></span>
          </li>
        ))}
      </ul>
    </div>
  );
}
