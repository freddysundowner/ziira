/** Dates for the public page, on the business's own clock. */
export function todayIn(zone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}

export function addDay(day: string, n: number): string {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/** "Tue 20 Oct": a day as a person reads it (the language of the page). */
export function dayLabel(day: string, language: string): string {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  return new Intl.DateTimeFormat(language, { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(Date.UTC(y, m - 1, d)));
}

export function timeLabel(iso: string, zone: string, language: string): string {
  return new Intl.DateTimeFormat(language, { hour: "2-digit", minute: "2-digit", timeZone: zone }).format(new Date(iso));
}

export function longLabel(iso: string, zone: string, language: string): string {
  return new Intl.DateTimeFormat(language, { dateStyle: "full", timeStyle: "short", timeZone: zone }).format(new Date(iso));
}
