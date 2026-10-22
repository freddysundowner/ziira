/**
 * Test kit for Home widgets: a fake API (a table from path to reply), a fake company and session, and a renderer with a router and a
 * query client. A test file mocks the SDK once:
 *   vi.mock("@/sdk", async (original) => (await import("@/test/widgetKit")).withFakes(await original()));
 * then sets `fake.routes["/api/v1/..."] = () => data` (or `() => new Error("message")` for a failed request) and renders the widget.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach } from "vitest";

export const COMPANY = { id: "c1", name: "Test Co", currency: "KES", timezone: "Africa/Nairobi", branches: [{ id: "b1", name: "Main" }] };

export const fake: { routes: Record<string, (query: unknown) => unknown>; units: Set<string>; calls: Array<{ path: string; query: unknown }> } = { routes: {}, units: new Set(), calls: [] };

afterEach(() => { cleanup(); fake.routes = {}; fake.units = new Set(); fake.calls = []; });

/** The SDK with its network and session parts replaced by the fakes above. */
export function withFakes<T extends object>(original: T): T {
  const GET = async (path: string, options?: { params?: { query?: unknown } }) => {
    const query = options?.params?.query;
    fake.calls.push({ path, query });
    const route = fake.routes[path];
    if (!route) return { data: undefined, error: { message: `no fake for ${path}` }, response: { ok: false, status: 500 } };
    const reply = route(query);
    return reply instanceof Error ? { data: undefined, error: { message: reply.message }, response: { ok: false, status: 500 } } : { data: reply, error: undefined, response: { ok: true, status: 200 } };
  };
  return {
    ...original,
    api: { GET },
    useCompany: () => ({ company: COMPANY, companies: [COMPANY], isLoading: false }),
    useCurrency: () => COMPANY.currency,
    useSession: () => ({ enabledUnits: fake.units }),
  };
}

export function renderWidget(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}
