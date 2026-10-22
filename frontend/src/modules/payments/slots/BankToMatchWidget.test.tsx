import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fake, renderWidget } from "@/test/widgetKit";

import payments from "../module";
import BankToMatchWidget from "./BankToMatchWidget";

vi.mock("@/sdk", async (original) => (await import("@/test/widgetKit")).withFakes(await original()));

const TXNS = "/api/v1/payments/transactions";
const txn = (id: string, amount: string) => ({ id, external_ref: `REF${id}`, counterparty_name: `Payer ${id}`, bill_ref: null, amount, match_status: "unmatched" });
const byStatus = (unmatched: object[] | Error, proposed: object[] = []) => (q: unknown) => ((q as { match_status: string }).match_status === "unmatched" ? unmatched : proposed);

describe("Bank to match", () => {
  it("is registered behind payments.view", () => {
    expect((payments.slots?.["dashboard.widgets"] ?? []).map((w) => [w.label, w.permission])).toContainEqual(["payments:bankToMatch.title", "payments.view"]);
  });
  it("counts transactions with no payment matched, and the suggested matches waiting for a yes", async () => {
    fake.routes[TXNS] = byStatus([txn("1", "500"), txn("2", "750")], [txn("3", "10")]);
    renderWidget(<BankToMatchWidget variant="stat" />);
    expect(await screen.findByText("2")).toBeTruthy();
    expect(screen.getByText("bankToMatch.suggested")).toBeTruthy();
    expect(fake.calls.map((c) => (c.query as { match_status: string }).match_status).sort()).toEqual(["proposed", "unmatched"]);
  });
  it("lists who paid and how much in the full box", async () => {
    fake.routes[TXNS] = byStatus([txn("1", "500")]);
    renderWidget(<BankToMatchWidget variant="full" />);
    expect((await screen.findByRole("listitem")).textContent).toContain("Payer 1");
  });
  it("collapses only when nothing is unmatched and nothing is suggested, and shows errors", async () => {
    fake.routes[TXNS] = byStatus([]);
    const first = renderWidget(<BankToMatchWidget variant="full" />);
    await waitFor(() => expect(first.container.querySelector("[data-clear]")?.textContent).toBe("bankToMatch.nothing"));
    first.unmount();
    fake.routes[TXNS] = byStatus([], [txn("3", "10")]);
    const second = renderWidget(<BankToMatchWidget variant="full" />);
    await screen.findByText("bankToMatch.suggested");
    expect(second.container.querySelector("[data-clear]")).toBeNull();
    second.unmount();
    fake.routes[TXNS] = byStatus(new Error("Down"));
    renderWidget(<BankToMatchWidget variant="full" />);
    expect((await screen.findByRole("alert")).textContent).toContain("Down");
  });
});
