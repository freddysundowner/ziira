import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
vi.mock("../api", async (original) => ({ ...(await original<typeof import("../api")>()), api: { GET: (...a: unknown[]) => get(...a), POST: (...a: unknown[]) => post(...a), PATCH: (...a: unknown[]) => patch(...a) } }));
const send = vi.fn();
vi.mock("./upload", () => ({ uploadFile: (...a: unknown[]) => send(...a), shrinkIfLarge: (f: File) => Promise.resolve(f) }));

import { ApiError } from "../api";
import { Attachments } from "./Attachments";

const settings = { entity_type: "jobs.job", entity_label: "Job", can_add: true, photo_consent: false, count: 0, max_per_record: 60, max_file_bytes: 10 * 1024 * 1024,
  accepted: ["image/jpeg"], categories: [{ key: "intake", label: "Intake" }, { key: "damage", label: "Damage" }] };
const file = (id: string, extra: Record<string, unknown> = {}) => ({ id, entity_type: "jobs.job", entity_id: "j1", company_id: "c1", category: "intake", caption: "", visibility: "staff", consent_note: "",
  kind: "image", content_type: "image/jpeg", name: `${id}.jpg`, size_bytes: 1000, width: 640, height: 480, page_count: null, location_stripped: true, created_at: "2026-10-18T10:00:00Z",
  created_by_name: "Wanjiru", thumb_url: `/t/${id}`, web_url: `/w/${id}`, ...extra });
const answer = (data: unknown) => Promise.resolve({ data, error: undefined, response: { ok: true, status: 200 } });
const refuse = (status: number, message = "No") => Promise.resolve({ data: undefined, error: { message }, response: { ok: false, status } });

function serve(files: unknown[], config: unknown = settings) {
  get.mockImplementation((path: string) => (path === "/api/v1/files/config" ? answer(config) : answer(files)));
}
function show() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Attachments entityType="jobs.job" entityId="j1" /></QueryClientProvider>);
}
const pick = (testId: string, ...files: File[]) => fireEvent.change(screen.getByTestId(testId), { target: { files } });
const jpg = (name = "front.jpg", size = 1000) => new File([new Uint8Array(size)], name, { type: "image/jpeg" });

beforeEach(() => { vi.useRealTimers(); });
afterEach(() => { cleanup(); get.mockReset(); post.mockReset(); patch.mockReset(); send.mockReset(); });

describe("Attachments", () => {
  it("invites the first photo when there are none", async () => {
    serve([]);
    show();
    expect(await screen.findByText("No photos or files yet")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Take photo/ })).toBeTruthy();
  });

  it("shows the files grouped by kind, with a mark for staff only and shareable", async () => {
    serve([file("a"), file("b", { category: "damage", caption: "Front left", visibility: "shareable" })]);
    show();
    expect(await screen.findByRole("heading", { name: /Intake/ })).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Damage/ })).toBeTruthy();
    expect(screen.getByAltText("Front left").getAttribute("src")).toBe("/t/b");
    expect(screen.getByTitle("Can be shared")).toBeTruthy();
    expect(screen.getByTitle("Staff only")).toBeTruthy();
  });

  it("shows nothing to someone who may not open the record, and an error with retry for other failures", async () => {
    get.mockImplementation(() => refuse(403));
    const { container } = show();
    await waitFor(() => expect(get).toHaveBeenCalled());
    await waitFor(() => expect(container.textContent).toBe(""));
    cleanup();
    get.mockReset();
    get.mockImplementation(() => refuse(500, "Server down"));
    show();
    expect(await screen.findByText("The photos and files could not be loaded.")).toBeTruthy();
    expect(screen.getByText("Server down")).toBeTruthy();
  });

  it("hides the add buttons from someone who may only look", async () => {
    serve([file("a")], { ...settings, can_add: false });
    show();
    await screen.findByAltText("a.jpg");
    expect(screen.queryByRole("button", { name: /Take photo/ })).toBeNull();
  });

  it("refuses a file that cannot be stored and says why, without sending it", async () => {
    serve([]);
    show();
    await screen.findByText("No photos or files yet");
    pick("file-input", new File(["x"], "setup.exe", { type: "application/x-msdownload" }), new File(["x"], "big.jpg", { type: "image/jpeg" }));
    expect(await screen.findByText("setup.exe is not a photo (JPEG, PNG, WebP) or a PDF.")).toBeTruthy();
    expect(send).toHaveBeenCalledTimes(1);                                      // the picture went; the program did not
  });

  it("sends a chosen photo with the selected kind and refreshes the list when it is stored", async () => {
    serve([]);
    send.mockResolvedValue(file("new"));
    show();
    await screen.findByText("No photos or files yet");
    fireEvent.change(screen.getByLabelText("Kind of photo"), { target: { value: "damage" } });
    pick("camera-input", jpg("IMG_1.jpg"));
    await waitFor(() => expect(send).toHaveBeenCalled());
    expect(send.mock.calls[0]![0]).toMatchObject({ entityType: "jobs.job", entityId: "j1", name: "IMG_1.jpg", category: "damage", visibility: "staff" });
    const calls = get.mock.calls.filter((c) => c[0] === "/api/v1/files").length;
    await waitFor(() => expect(get.mock.calls.filter((c) => c[0] === "/api/v1/files").length).toBeGreaterThan(calls - 1));
  });

  it("keeps a photo that could not be sent, waits, and sends it again by itself when the connection returns", async () => {
    serve([]);
    send.mockRejectedValueOnce(new ApiError("Cannot reach the server.", 0)).mockResolvedValue(file("late"));
    show();
    await screen.findByText("No photos or files yet");
    pick("file-input", jpg("signal.jpg"));
    expect(await screen.findByText("No connection. This will be sent again by itself.")).toBeTruthy();
    expect(screen.getByText("signal.jpg")).toBeTruthy();
    await act(async () => { window.dispatchEvent(new Event("online")); });
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls[1]![0].key).toBe(send.mock.calls[0]![0].key);       // the same key: never stored twice
    await waitFor(() => expect(screen.queryByText("signal.jpg")).toBeNull());
  });

  it("stops on a refusal a person must fix and offers a manual retry", async () => {
    serve([]);
    send.mockRejectedValueOnce(new ApiError("This is not a photo (JPEG, PNG or WebP) or a PDF", 422)).mockResolvedValue(file("ok"));
    show();
    await screen.findByText("No photos or files yet");
    pick("file-input", jpg("odd.jpg"));
    expect(await screen.findByText(/This is not a photo/)).toBeTruthy();
    expect(send).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /Try again/ }));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
  });

  it("opens the viewer, saves a caption and a visibility change, and deletes only with a reason", async () => {
    serve([file("a", { caption: "Old" }), file("b")]);
    patch.mockImplementation((_path: string, init: { body: Record<string, unknown> }) => answer({ ...file("a", { caption: "Old" }), ...init.body }));
    post.mockImplementation(() => Promise.resolve({ data: undefined, error: undefined, response: { ok: true, status: 204 } }));
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Old" }));
    const dialog = await screen.findByRole("dialog", { name: "a.jpg" });
    const caption = within(dialog).getByLabelText("Caption");
    fireEvent.change(caption, { target: { value: "Rusted bumper" } });
    fireEvent.blur(caption);
    await waitFor(() => expect(patch).toHaveBeenCalled());
    expect(patch.mock.calls[0]![1].body).toEqual({ caption: "Rusted bumper" });
    fireEvent.click(within(dialog).getByRole("switch", { name: "Can be shared" }));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(2));
    expect(patch.mock.calls[1]![1].body).toEqual({ visibility: "shareable" });
    fireEvent.click(within(dialog).getByRole("button", { name: /Delete/ }));
    const ask = await screen.findByRole("dialog", { name: "Delete this file?" });
    const confirm = within(ask).getByRole("button", { name: "Delete" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(within(ask).getByLabelText("Why is it removed?"), { target: { value: "Wrong job" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(post.mock.calls[0]![0]).toBe("/api/v1/files/{file_id}/delete");
    expect(post.mock.calls[0]![1].body).toEqual({ reason: "Wrong job" });
  });

  it("is read only in the viewer for someone who may not edit, and offers a PDF as a document", async () => {
    serve([file("p", { kind: "pdf", content_type: "application/pdf", name: "estimate.pdf", thumb_url: null, web_url: null, page_count: 2 })], { ...settings, can_add: false });
    show();
    fireEvent.click(await screen.findByRole("button", { name: "estimate.pdf" }));
    const dialog = await screen.findByRole("dialog", { name: "estimate.pdf" });
    expect(within(dialog).getByText("PDF, 2 pages")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: /Open the PDF/ })).toBeTruthy();
    expect((within(dialog).getByLabelText("Caption") as HTMLInputElement).disabled).toBe(true);
    expect(within(dialog).queryByRole("button", { name: /Delete/ })).toBeNull();
  });

  it("asks for the customer's consent where the record needs it, and sends it with the photo", async () => {
    serve([], { ...settings, photo_consent: true });
    send.mockResolvedValue(file("c"));
    show();
    await screen.findByText("No photos or files yet");
    fireEvent.change(screen.getByLabelText("Customer agreed to be photographed"), { target: { value: "Jane, in person" } });
    pick("camera-input", jpg());
    await waitFor(() => expect(send).toHaveBeenCalled());
    expect(send.mock.calls[0]![0].consent).toBe("Jane, in person");
  });
});
