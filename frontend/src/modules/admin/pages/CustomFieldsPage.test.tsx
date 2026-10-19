import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const patch = vi.fn();
const post = vi.fn();
const del = vi.fn();
const put = vi.fn();
vi.mock("@/sdk/api", async (original) => ({
  ...(await original<typeof import("@/sdk/api")>()),
  api: { GET: (...a: unknown[]) => get(...a), PATCH: (...a: unknown[]) => patch(...a), POST: (...a: unknown[]) => post(...a), DELETE: (...a: unknown[]) => del(...a), PUT: (...a: unknown[]) => put(...a) },
}));

import { addModuleTranslations, type ModuleDefinition } from "@/sdk";

import enFields from "../i18n/en.fields.json";
import swFields from "../i18n/sw.fields.json";
import CustomFieldsPage from "./CustomFieldsPage";

addModuleTranslations([{ unit: "kernel", translations: { en: enFields, sw: swFields } } as unknown as ModuleDefinition]);

afterEach(() => { cleanup(); [get, patch, post, del, put].forEach((m) => m.mockReset()); });

const ok = (data: unknown) => Promise.resolve({ data, error: undefined, response: { ok: true, status: 200 } });
const nothing = () => Promise.resolve({ data: undefined, error: undefined, response: { ok: true, status: 204 } });
const entities = [{ entity_type: "bookings.asset", label: "Vehicle or item", unit: "bookings", view_permission: "a", edit_permission: "b" }, { entity_type: "crm.customer", label: "Customer", unit: "crm", view_permission: "a", edit_permission: "b" }];
const field = (id: string, entity_type: string, extra: Record<string, unknown> = {}) => ({
  id, company_id: null, entity_type, key: id, label: id.toUpperCase(), kind: "text", choices: [], required: false, searchable: false, sort_order: 10, active: true, source: "business", from_pack: false, ...extra,
});

function serve(fields: unknown[]) {
  get.mockImplementation((path: string) => ok(path.endsWith("/entities") ? entities : fields));
}
function show() {
  return render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><CustomFieldsPage /></QueryClientProvider></MemoryRouter>);
}

describe("Settings > Custom fields", () => {
  it("groups the fields by kind of record and gives an empty record type a way to add the first one", async () => {
    serve([field("plate", "bookings.asset", { required: true }), field("note", "bookings.asset", { sort_order: 20 })]);
    show();
    const card = (await screen.findByText("Vehicle or item")).closest("section, div[class*='rounded']") as HTMLElement;
    expect(within(card.parentElement as HTMLElement).getByText("PLATE")).toBeTruthy();
    expect(screen.getByText("Required")).toBeTruthy();
    expect(screen.getByText(/No extra details for customer yet/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Add a field" })).toHaveLength(2);
  });
  it("marks a field that came with a pack: it can be hidden but not deleted", async () => {
    serve([field("plate", "bookings.asset", { from_pack: true, source: "pack:pack_garage" }), field("mine", "bookings.asset", { sort_order: 20 })]);
    show();
    await screen.findByText("PLATE");
    expect(screen.getByText("From an industry pack")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delete PLATE" })).toBeNull();
    expect(screen.getByRole("button", { name: "Hide PLATE" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Delete MINE" })).toBeTruthy();
  });
  it("hides a field with one click", async () => {
    serve([field("plate", "bookings.asset")]);
    patch.mockImplementation(() => ok(field("plate", "bookings.asset", { active: false })));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Hide PLATE" }));
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect((patch.mock.calls[0][1] as { body: unknown }).body).toEqual({ active: false });
  });
  it("asks before deleting and then deletes", async () => {
    serve([field("plate", "bookings.asset")]);
    del.mockImplementation(nothing);
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Delete PLATE" }));
    expect(del).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete field" }));
    await waitFor(() => expect(del).toHaveBeenCalledTimes(1));
  });
  it("moves a field down by saving the new order", async () => {
    serve([field("one", "bookings.asset", { sort_order: 10 }), field("two", "bookings.asset", { sort_order: 20 })]);
    put.mockImplementation(nothing);
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Move ONE down" }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    expect((put.mock.calls[0][1] as { body: unknown }).body).toEqual({ entity_type: "bookings.asset", ids: ["two", "one"] });
    expect((screen.getByRole("button", { name: "Move ONE up" }) as HTMLButtonElement).disabled).toBe(true);
  });
  it("adds a field: the short code follows the name, a choice needs choices, and the request carries them", async () => {
    serve([]);
    post.mockImplementation(() => ok(field("hair_type", "bookings.asset")));
    show();
    fireEvent.click((await screen.findAllByRole("button", { name: "Add a field" }))[0]);
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: "Hair type" } });
    expect((screen.getByLabelText(/Short code/) as HTMLInputElement).value).toBe("hair_type");
    fireEvent.change(screen.getByLabelText(/Kind of answer/), { target: { value: "choice" } });
    expect(save.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/The choices/), { target: { value: "Straight\nCurly\n" } });
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    expect((post.mock.calls[0][1] as { body: unknown }).body).toEqual({
      entity_type: "bookings.asset", key: "hair_type", label: "Hair type", kind: "choice", choices: ["Straight", "Curly"], required: false, searchable: false,
    });
  });
  it("offers a retry when the lists cannot be loaded", async () => {
    get.mockImplementationOnce(() => Promise.resolve({ data: undefined, error: { message: "boom" }, response: { ok: false, status: 500 } }));
    get.mockImplementation((path: string) => ok(path.endsWith("/entities") ? entities : []));
    show();
    fireEvent.click(await screen.findByRole("button", { name: /try again|retry/i }));
    await screen.findByText("Vehicle or item");
  });
});
