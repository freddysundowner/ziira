/** Small pure helpers behind the console's inline SVG charts (no chart library). Numbers in, path strings out. */

/** Round a maximum up to a tidy axis end: 1, 2, 5 or 10 times a power of ten (0 gives 1, so an empty chart still has an axis). */
export function niceMax(max: number): number {
  if (!Number.isFinite(max) || max <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(max));
  const unit = max / power;
  const step = unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10;
  return step * power;
}

/** Evenly spaced axis values from 0 to the (nice) maximum, `count` + 1 of them. */
export function ticks(max: number, count = 4): number[] {
  const top = niceMax(max);
  return Array.from({ length: count + 1 }, (_, i) => (top * i) / count);
}

export interface Box {
  width: number;
  height: number;
  left: number;
  right: number;
  top: number;
  bottom: number;
}

const round = (n: number) => Math.round(n * 100) / 100;

/** The x position of point `i` of `n` inside the plot area (a single point sits in the middle). */
export function xAt(i: number, n: number, box: Box): number {
  const inner = box.width - box.left - box.right;
  return round(n <= 1 ? box.left + inner / 2 : box.left + (inner * i) / (n - 1));
}

/** The y position of a value on an axis from 0 to `max` (zero at the bottom). */
export function yAt(value: number, max: number, box: Box): number {
  const inner = box.height - box.top - box.bottom;
  return round(box.top + inner - (inner * Math.min(Math.max(value, 0), max)) / max);
}

export function linePath(values: number[], max: number, box: Box): string {
  return values.map((v, i) => `${i === 0 ? "M" : "L"}${xAt(i, values.length, box)} ${yAt(v, max, box)}`).join(" ");
}

/** The line closed down to the axis, for a filled area. */
export function areaPath(values: number[], max: number, box: Box): string {
  if (values.length === 0) return "";
  const base = round(box.height - box.bottom);
  return `${linePath(values, max, box)} L${xAt(values.length - 1, values.length, box)} ${base} L${xAt(0, values.length, box)} ${base} Z`;
}

/** Which point is nearest to a pointer x (in the same units as the box). */
export function nearestIndex(x: number, n: number, box: Box): number {
  if (n <= 1) return 0;
  const inner = box.width - box.left - box.right;
  return Math.min(n - 1, Math.max(0, Math.round(((x - box.left) / inner) * (n - 1))));
}

/** Donut slices: each has its share (0-1) and the SVG path of its ring segment. A single full slice becomes two halves so it can be drawn. */
export function donutSlices(values: number[], radius: number, hole: number): { share: number; path: string }[] {
  const total = values.reduce((a, b) => a + b, 0);
  if (total <= 0) return [];
  const cx = radius;
  const point = (angle: number, r: number) => `${round(cx + r * Math.sin(angle))} ${round(cx - r * Math.cos(angle))}`;
  let start = 0;
  return values.map((value) => {
    const share = value / total;
    const full = share >= 0.9999;
    const end = start + (full ? Math.PI * 2 - 0.0001 : share * Math.PI * 2);
    const large = end - start > Math.PI ? 1 : 0;
    const path = `M${point(start, radius)} A${radius} ${radius} 0 ${large} 1 ${point(end, radius)} L${point(end, hole)} A${hole} ${hole} 0 ${large} 0 ${point(start, hole)} Z`;
    start = end;
    return { share, path };
  });
}

/** A sentence a screen reader can read for a series: "Jan 2030: 5, Feb 2030: 7". */
export function describeSeries(labels: string[], values: number[], format: (n: number) => string): string {
  return labels.map((l, i) => `${l}: ${format(values[i] ?? 0)}`).join(", ");
}

/** The change from the first to the last value, as a share of the first (null when it cannot be told). */
export function trend(values: number[]): number | null {
  const first = values[0];
  const last = values[values.length - 1];
  if (first === undefined || last === undefined || first === 0) return null;
  return (last - first) / first;
}
