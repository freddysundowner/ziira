import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { fake, renderWidget } from "@/test/widgetKit";

import claims from "../module";
import ClaimsWaitingWidget from "./ClaimsWaitingWidget";

vi.mock("@/sdk", async (original) => (await import("@/test/widgetKit")).withFakes(await original()));
vi.mock("../hooks", () => ({ useClaimsCompany: () => ({ companyId: "c1" }) }));

const LIST = "/api/v1/claims/claims";
const claim = (id: string, waiting_on: string | null) => ({ id, number: `C-${id}`, payer_name: "Madison Insurance", waiting_on, status: "open" });

describe("Claims waiting", () => {
  it("is registered behind claims.view", () => {
    expect((claims.slots?.["dashboard.widgets"] ?? []).map((w) => [w.label, w.permission])).toContainEqual(["claims:widget.title", "claims.view"]);
  });
  it("counts claims waiting on the payer and on us, not the ones nobody waits for", async () => {
    fake.routes[LIST] = () => [claim("1", "payer"), claim("2", "us"), claim("3", null), claim("4", "customer")];
    renderWidget(<ClaimsWaitingWidget variant="stat" />);
    expect(await screen.findByText("2")).toBeTruthy();
    expect(screen.getByText("widget.toAnswer")).toBeTruthy();
    expect(fake.calls[0].query).toMatchObject({ company_id: "c1", open_only: true });
  });
  it("puts the counters to answer first in the full box", async () => {
    fake.routes[LIST] = () => [claim("1", "payer"), claim("2", "us")];
    renderWidget(<ClaimsWaitingWidget variant="full" />);
    const rows = await screen.findAllByRole("listitem");
    expect(rows[0].textContent).toContain("C-2");
    expect(rows[0].textContent).toContain("widget.answerNeeded");
  });
  it("collapses to all clear and shows errors", async () => {
    fake.routes[LIST] = () => [claim("3", null)];
    const first = renderWidget(<ClaimsWaitingWidget variant="full" />);
    await waitFor(() => expect(first.container.querySelector("[data-clear]")?.textContent).toBe("widget.nothing"));
    first.unmount();
    fake.routes[LIST] = () => new Error("Not allowed");
    renderWidget(<ClaimsWaitingWidget variant="stat" />);
    expect((await screen.findByRole("alert")).textContent).toContain("Not allowed");
  });
});
