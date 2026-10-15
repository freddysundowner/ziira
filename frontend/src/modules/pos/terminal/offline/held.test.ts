import { describe, expect, it } from "vitest";

import type { HeldSale } from "../cart";
import { applyReconciled, fromServer, reconcileHeld, type ServerHeld, toServerBody } from "./held";

const local = (id: string, remote = false, savedAt = "2026-01-01T10:00:00Z"): HeldSale => ({
  id, label: `Sale ${id}`, savedAt, customerId: "", customerName: "", customerPhone: "", remote,
  lines: [{ key: "k" + id, productId: "p1", sku: "CEM", name: "Cement", listPrice: "116.00", price: "116.00", quantity: "2", discount: "0", reasonId: "", stock: "", vatRate: "16" }],
});
const server = (id: string): ServerHeld => ({
  id: "s" + id, local_id: id, till_session_id: "t", label: `Sale ${id}`, customer_id: null, customer_name: "", customer_phone: "", note: null, status: "held", created_at: "2026-01-01T11:00:00Z",
  lines: [{ product_id: "p1", sku: "CEM", name: "Cement", quantity: "2", list_price: "116.00", price: "116.00", discount: "0", reason_code_id: null }],
});

describe("held sales on this device and at the server", () => {
  it("marks what both have as at the server", () => {
    const r = reconcileHeld([local("a")], [server("a")], new Set());
    expect([...r.remote]).toEqual(["a"]);
    expect(r.upload).toEqual([]);
    expect(r.add).toEqual([]);
  });
  it("sends what was held offline", () => {
    const r = reconcileHeld([local("a")], [], new Set());
    expect(r.upload.map((h) => h.id)).toEqual(["a"]);
  });
  it("drops what the server let go of (resumed or discarded elsewhere)", () => {
    const r = reconcileHeld([local("a", true)], [], new Set());
    expect([...r.drop]).toEqual(["a"]);
    expect(r.upload).toEqual([]);
  });
  it("brings back what only the server has (this device lost its copy)", () => {
    const r = reconcileHeld([], [server("b")], new Set());
    expect(r.add).toHaveLength(1);
    expect(r.add[0]).toMatchObject({ id: "b", remote: true, label: "Sale b" });
    expect(r.add[0]!.lines[0]).toMatchObject({ productId: "p1", quantity: "2", price: "116.00" });
  });
  it("leaves out what the cashier resumed or discarded here and the server has not been told yet", () => {
    const r = reconcileHeld([local("a", true)], [server("a"), server("b")], new Set(["a", "b"]));
    expect([...r.remote]).toEqual([]);
    expect(r.add).toEqual([]);
    expect(r.drop.size).toBe(0);
  });
  it("applies to the list as it is now: a sale held while this ran is not lost", () => {
    const r = reconcileHeld([local("a", true)], [server("a"), server("b")], new Set());
    const now = [local("a", false), local("fresh")];
    const next = applyReconciled(now, r);
    expect(next.map((h) => h.id).sort()).toEqual(["a", "b", "fresh"]);
    expect(next.find((h) => h.id === "a")?.remote).toBe(true);
    expect(next.find((h) => h.id === "fresh")?.remote).toBeFalsy();
  });
  it("does not add the same sale twice, and orders newest first", () => {
    const r = reconcileHeld([], [server("b")], new Set());
    const next = applyReconciled([local("b"), local("c", false, "2026-01-02T00:00:00Z")], r);
    expect(next.map((h) => h.id)).toEqual(["c", "b"]);
  });
});

describe("a held sale in the server's shape", () => {
  it("uses the terminal's id as the idempotent local id and keeps prices and reasons", () => {
    const h = local("a");
    h.lines[0]!.reasonId = "r1";
    h.customerId = "c1";
    const body = toServerBody(h);
    expect(body).toMatchObject({ local_id: "a", customer_id: "c1", label: "Sale a" });
    expect(body.lines[0]).toEqual({ product_id: "p1", sku: "CEM", name: "Cement", quantity: "2", list_price: "116.00", price: "116.00", discount: "0", reason_code_id: "r1" });
  });
  it("round-trips through the server's shape", () => {
    const back = fromServer(server("a"));
    expect(toServerBody(back).lines[0]).toMatchObject({ product_id: "p1", quantity: "2", price: "116.00" });
  });
});
