/** The payer's response page requests: plain fetch, no sign-in, no access token. */
import type { Schemas } from "@/sdk";

export type PublicEstimate = Schemas["ClaimsPublicEstimateOut"];
export type PublicLine = Schemas["ClaimsPublicLineOut"];
export type PublicPhoto = Schemas["ClaimsPublicPhotoOut"];

export class ResponseError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

const url = (token: string) => `/api/v1/claims/public/claim-response/${encodeURIComponent(token)}`;

async function call<T>(target: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(target, init);
  } catch {
    throw new ResponseError("offline", 0);
  }
  const body = (await response.json().catch(() => ({}))) as { message?: string };
  if (!response.ok) throw new ResponseError(body.message ?? "error", response.status);
  return body as T;
}

export const loadEstimate = (token: string) => call<PublicEstimate>(url(token));

export interface AnswerBody {
  name: string;
  role?: string | null;
  note?: string | null;
  authority_ref?: string | null;
  authority_amount?: string | null;
  lines: { line_id: string; state: "approved" | "countered" | "rejected" | "needs_information"; amount?: string | null; reason?: string | null }[];
}

export const answerEstimate = (token: string, body: AnswerBody) =>
  call<{ state: string; response: string | null }>(url(token), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
