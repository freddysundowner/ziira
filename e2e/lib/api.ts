/** A small client for the Ziira API, used to set up data quickly; the journeys do the thing under test in the browser. */
import { randomUUID } from "node:crypto";

export const API_URL = process.env.E2E_API_URL ?? "http://localhost:8765";

export interface Account {
  email: string;
  password: string;
  name: string;
}

export class ApiError extends Error {
  constructor(public status: number, public body: unknown, message: string) {
    super(message);
  }
}

export class Api {
  private token = "";
  private device = randomUUID();
  constructor(public account: Account) {}

  async signIn(): Promise<this> {
    const res = await fetch(`${API_URL}/api/v1/auth/sign-in`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ login: this.account.email, password: this.account.password, device_id: this.device }),
    });
    const body = (await res.json()) as { access_token?: string };
    if (!res.ok || !body.access_token) throw new ApiError(res.status, body, `sign-in failed: ${JSON.stringify(body)}`);
    this.token = body.access_token;
    return this;
  }

  async call<T = any>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
    for (let attempt = 0; attempt < 2; attempt++) {
      const res = await fetch(`${API_URL}/api/v1${path}`, {
        method,
        headers: { authorization: `Bearer ${this.token}`, "content-type": "application/json", ...headers },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      if (res.status === 401 && attempt === 0) {
        await this.signIn();
        continue;
      }
      const text = await res.text();
      const data = text ? JSON.parse(text) : null;
      if (!res.ok) throw new ApiError(res.status, data, `${method} ${path} -> ${res.status} ${text.slice(0, 400)}`);
      return data as T;
    }
    throw new Error("unreachable");
  }
  /** The HTTP status a GET gets (to check that something is refused), without throwing. */
  async statusOf(path: string): Promise<number> {
    const res = await fetch(`${API_URL}/api/v1${path}`, { headers: { authorization: `Bearer ${this.token}` } });
    await res.text();
    return res.status;
  }
  get = <T = any>(path: string) => this.call<T>("GET", path);
  post = <T = any>(path: string, body?: unknown, headers?: Record<string, string>) => this.call<T>("POST", path, body ?? {}, headers);
  put = <T = any>(path: string, body: unknown) => this.call<T>("PUT", path, body);
  patch = <T = any>(path: string, body: unknown) => this.call<T>("PATCH", path, body);
}

/** Register a business through the API (the same two steps the web form does) and return the owner's account. */
export async function registerBusiness(name: string, email: string, password: string): Promise<Account & { business: string }> {
  const res = await fetch(`${API_URL}/api/v1/register`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ business_name: name, owner_name: "Olive Owner", email, password, currency: "USD", phone_country_code: "44", country: "GB" }),
  });
  const started = (await res.json()) as { dev_token?: string };
  if (!res.ok || !started.dev_token) throw new Error(`register failed: ${res.status} ${JSON.stringify(started)}`);
  const verify = await fetch(`${API_URL}/api/v1/register/verify`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ token: started.dev_token, device_id: randomUUID() }),
  });
  if (!verify.ok) throw new Error(`verify failed: ${verify.status} ${await verify.text()}`);
  return { email, password, name: "Olive Owner", business: name };
}

export const unique = (prefix: string) => `${prefix}${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
