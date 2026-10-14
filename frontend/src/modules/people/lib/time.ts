const two = (n: number) => String(n).padStart(2, "0");

/** An ISO timestamp from the API as the value of a datetime-local input (the browser's own time zone). */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}T${two(d.getHours())}:${two(d.getMinutes())}`;
}

/** A datetime-local value back to the ISO timestamp the API wants; empty stays null. */
export function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/** "08:30:00" from a time field of the API to "08:30". */
export const shortTime = (value: string | null | undefined): string => (value ? value.slice(0, 5) : "—");

/** Hours with at most two decimals and no trailing zeros ("7.5"). */
export const hoursText = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? String(Math.round(n * 100) / 100) : String(value);
};
