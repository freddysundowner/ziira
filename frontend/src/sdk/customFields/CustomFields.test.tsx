import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const put = vi.fn();
vi.mock("../api", async (original) => ({ ...(await original<typeof import("../api")>()), api: { GET: (...a: unknown[]) => get(...a), PUT: (...a: unknown[]) => put(...a) } }));

import { CustomFields, CustomFieldsForm } from "./CustomFields";
import type { CustomFieldDef } from "./logic";

afterEach(() => { cleanup(); get.mockReset(); put.mockReset(); });

const def = (key: string, kind: CustomFieldDef["kind"], extra: Partial<CustomFieldDef> = {}): CustomFieldDef => ({
  id: key, company_id: null, entity_type: "bookings.asset", key, label: key.replace("_", " "), kind, choices: [], required: false, searchable: false,
  sort_order: 0, active: true, source: "business", from_pack: false, ...extra,
});
const answer = (data: unknown) => Promise.resolve({ data, error: undefined, response: { ok: true, status: 200 } });
const refuse = (status: number) => Promise.resolve({ data: undefined, error: { detail: "No" }, response: { ok: false, status } });

function show(canEdit = true) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><CustomFields entityType="bookings.asset" entityId="a1" canEdit={canEdit} /></QueryClientProvider>);
}

describe("CustomFieldsForm", () => {
  const fields = [def("plate", "text", { required: true }), def("seats", "number"), def("serviced", "date"), def("insured", "bool"), def("fuel", "choice", { choices: ["Petrol", "Diesel"] })];
  it("draws an input for each kind and reports changes by key", () => {
    const changes: [string, string][] = [];
    render(<CustomFieldsForm fields={fields} values={{}} onChange={(k, v) => changes.push([k, v])} />);
    fireEvent.change(screen.getByLabelText(/plate/), { target: { value: "KAA 1" } });
    fireEvent.change(screen.getByLabelText(/seats/), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText(/seats/), { target: { value: "5x" } });      // letters are not accepted in a number
    fireEvent.change(screen.getByLabelText(/serviced/), { target: { value: "2026-02-01" } });
    fireEvent.change(screen.getByLabelText(/insured/), { target: { value: "true" } });
    fireEvent.change(screen.getByLabelText(/fuel/), { target: { value: "Diesel" } });
    expect(changes).toEqual([["plate", "KAA 1"], ["seats", "5"], ["serviced", "2026-02-01"], ["insured", "true"], ["fuel", "Diesel"]]);
  });
  it("shows a problem under its field and marks the required one", () => {
    render(<CustomFieldsForm fields={fields} values={{}} onChange={() => undefined} problems={{ plate: "required" }} />);
    expect(screen.getByRole("alert").textContent).toBe("This is needed.");
    expect(screen.getByLabelText(/plate/).getAttribute("aria-invalid")).toBe("true");
  });
  it("lists the values when read only, with yes or no for a yes/no field and a quiet note for what is not set", () => {
    render(<CustomFieldsForm fields={fields} values={{ plate: "KAA 1", insured: "false" }} onChange={() => undefined} readOnly />);
    expect(screen.getByText("KAA 1")).toBeTruthy();
    expect(screen.getByText("No")).toBeTruthy();
    expect(screen.getAllByText("Not set").length).toBe(3);
  });
  it("leaves out hidden fields", () => {
    render(<CustomFieldsForm fields={[def("old", "text", { active: false }), def("now", "text")]} values={{}} onChange={() => undefined} />);
    expect(screen.queryByLabelText(/old/)).toBeNull();
    expect(screen.getByLabelText(/now/)).toBeTruthy();
  });
});

describe("CustomFields on a record", () => {
  const loaded = { fields: [def("plate", "text", { required: true }), def("seats", "number")], values: { plate: "KAA 1" } };

  it("shows the saved values once the server answers", async () => {
    get.mockImplementation(() => answer(loaded));
    show();
    expect(screen.queryByText("KAA 1")).toBeNull();                 // nothing shown until the server answers
    await waitFor(() => expect(screen.getByText("KAA 1")).toBeTruthy());
  });
  it("shows nothing when the business defined no fields, and nothing when the person may not open the record", async () => {
    get.mockImplementation(() => answer({ fields: [], values: {} }));
    const { container } = show();
    await waitFor(() => expect(get).toHaveBeenCalled());
    await waitFor(() => expect(container.textContent).toBe(""));
    cleanup();
    get.mockImplementation(() => refuse(403));
    const second = show();
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(second.container.textContent).toBe(""));
  });
  it("offers a retry when loading fails", async () => {
    get.mockImplementationOnce(() => refuse(500)).mockImplementation(() => answer(loaded));
    show();
    fireEvent.click(await screen.findByRole("button", { name: /try again|retry/i }));
    await waitFor(() => expect(screen.getByText("KAA 1")).toBeTruthy());
  });
  it("has no Edit button for someone who may only look", async () => {
    get.mockImplementation(() => answer(loaded));
    show(false);
    await screen.findByText("KAA 1");
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });
  it("checks before saving, sends only what changed and shows the saved values", async () => {
    get.mockImplementation(() => answer(loaded));
    put.mockImplementation(() => answer({ fields: loaded.fields, values: { plate: "KAA 1", seats: "5" } }));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText(/plate/), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("alert").textContent).toBe("This is needed.");      // the required field is checked here first
    expect(put).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/plate/), { target: { value: "KAA 1" } });
    fireEvent.change(screen.getByLabelText(/seats/), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
    expect((put.mock.calls[0][1] as { body: unknown }).body).toEqual({ values: { seats: "5" } });
    await waitFor(() => expect(screen.getByText("5")).toBeTruthy());
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });
  it("keeps the form open and shows the server's message when saving is refused", async () => {
    get.mockImplementation(() => answer(loaded));
    put.mockImplementation(() => Promise.resolve({ data: undefined, error: { error: "validation", message: "Seats: enter a number" }, response: { ok: false, status: 422 } }));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByLabelText(/seats/), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.getByText(/enter a number/)).toBeTruthy());
    expect(screen.getByRole("button", { name: "Save" })).toBeTruthy();
  });
});
