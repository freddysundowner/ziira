/** The customer's estimate page requests: plain fetch, no sign-in, no access token. */
import type { Schemas } from "@/sdk";

export type PublicEstimate = Schemas["PublicEstimateOut"];

export class ApprovalError extends Error {
  constructor(message: string, readonly status: number) { super(message); }
}

const url = (token: string) => `/api/v1/jobs/public/job-approval/${encodeURIComponent(token)}`;

async function call<T>(target: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(target, init);
  } catch {
    throw new ApprovalError("offline", 0);
  }
  const body = (await response.json().catch(() => ({}))) as { message?: string };
  if (!response.ok) throw new ApprovalError(body.message ?? "error", response.status);
  return body as T;
}

export const loadEstimate = (token: string) => call<PublicEstimate>(url(token));

export const answerEstimate = (token: string, body: { approve: boolean; name: string; note?: string }) =>
  call<{ state: string }>(url(token), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
