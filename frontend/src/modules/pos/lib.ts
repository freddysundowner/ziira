/** Small pure helpers for the POS screens. The backend owns the money; these only prepare what is shown. */

const round4 = (n: number) => Math.round(n * 10_000) / 10_000;

/** Adds amounts for a display figure (a dashboard total). Values that are not numbers are ignored. */
export function sumAmounts(values: readonly (string | null | undefined)[]): number {
  return round4(values.reduce((sum, v) => sum + (Number.isFinite(Number(v)) && v !== "" && v != null ? Number(v) : 0), 0));
}

/** Counted minus expected, for a preview while someone types. Null until a number is typed. */
export function variancePreview(expected: string | null | undefined, counted: string): number | null {
  if (counted.trim() === "" || !Number.isFinite(Number(counted))) return null;
  return round4(Number(counted) - Number(expected ?? 0));
}

export interface ReturnLine {
  sale_line_id: string;
  quantity: string;
}

/** The lines someone chose to return (quantity above zero), in the shape the API wants. */
export function chosenReturnLines(quantities: Record<string, string>): ReturnLine[] {
  return Object.entries(quantities)
    .filter(([, q]) => Number(q) > 0)
    .map(([sale_line_id, quantity]) => ({ sale_line_id, quantity }));
}

/** Ids of lines where more is being returned than was sold. */
export function overReturned(quantities: Record<string, string>, sold: Record<string, string>): string[] {
  return Object.entries(quantities).filter(([id, q]) => Number(q) > Number(sold[id] ?? 0)).map(([id]) => id);
}

/** The first eight characters of an id, for when a name is not available. */
export const shortId = (id: string): string => id.slice(0, 8);
