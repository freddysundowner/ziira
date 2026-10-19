/** The public booking page's requests: plain fetch, no sign-in, no access token. */
import type { Schemas } from "@/sdk";

export type PublicPage = Schemas["PublicPageOut"];
export type PublicSlot = Schemas["PublicSlot"];
export type PublicBooked = Schemas["PublicBookingOut"];

export class PublicError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

const base = (slug: string) => `/api/v1/bookings/public/book/${encodeURIComponent(slug)}`;

async function call<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new PublicError("offline", 0);
  }
  const body = (await response.json().catch(() => ({}))) as { message?: string };
  if (!response.ok) throw new PublicError(body.message ?? "error", response.status);
  return body as T;
}

export const loadPage = (slug: string) => call<PublicPage>(base(slug));

export const loadSlots = (slug: string, service: string, date: string, resource?: string) =>
  call<PublicSlot[]>(`${base(slug)}/slots?service=${service}&date=${date}${resource ? `&resource=${resource}` : ""}`);

export interface BookingRequest {
  service_id: string; start: string; resource_id?: string; name: string; phone?: string; email?: string; note?: string; consent: boolean; website: string;
}

export const sendBooking = (slug: string, body: BookingRequest, key: string) =>
  call<PublicBooked>(`${base(slug)}/appointments`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key }, body: JSON.stringify(body) });
