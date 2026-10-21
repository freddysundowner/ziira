import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { addModuleTranslations, type ModuleDefinition } from "@/sdk";

import enApps from "../i18n/en.apps.json";
import swApps from "../i18n/sw.apps.json";
import { UnitCardView } from "./apps/UnitCardView";
import type { UnitCard } from "./apps/lib";

addModuleTranslations([{ unit: "kernel", translations: { en: enApps, sw: swApps } } as unknown as ModuleDefinition]);
afterEach(cleanup);

const pack: UnitCard = {
  name: "pack_salon", title: "Salon pack", description: "Salon services.", category: "industry", countries: [], editions: ["services"], kind: "plugin", version: "1.0.0",
  requires: ["products"], optional: [], dependants: [], installed: true, enabled: false, has_data: false, in_plan: true, will_also_enable: [], can_enable: true,
  can_disable: false, why_not_disable: null, can_remove: false, why_not_remove: null,
  sale_state: "included", sale_price: null, sale_currency: null, sale_tax_inclusive: false, bought_at: null, receipt_invoice_id: null, bought_free: false, can_buy: false,
};
const show = (props: { forEdition?: boolean; recommended?: boolean; unit?: UnitCard; supportEmail?: string; onBuy?: () => void }) =>
  render(<MemoryRouter><UnitCardView unit={props.unit ?? pack} all={[props.unit ?? pack]} onEnable={() => undefined} onDisable={() => undefined} onRemove={() => undefined} {...props} /></MemoryRouter>);

describe("an industry pack on the Add-ons page", () => {
  it("carries an Industry badge instead of the plugin one, in the same grid as the others", () => {
    show({});
    expect(screen.getByText("Industry")).toBeTruthy();
    expect(screen.queryByText("Plugin")).toBeNull();
    expect(screen.getByRole("button", { name: "Switch on" })).toBeTruthy();
  });
  it("says when it is recommended for the business's edition", () => {
    show({ forEdition: true });
    expect(screen.getByText("Recommended for your edition")).toBeTruthy();
    expect(screen.queryByText("Recommended")).toBeNull();
  });
});

const sellable: UnitCard = { ...pack, name: "jobs", title: "Jobs", category: "", editions: [], kind: "module", in_plan: false, can_enable: false, why_not_enable: "Not included in your plan.", sale_state: "for_sale", sale_price: "3000.00", sale_currency: "KES", can_buy: true };

describe("an add-on outside the plan", () => {
  it("offers the owner one payment and never says upgrade", () => {
    let bought = 0;
    show({ unit: sellable, onBuy: () => { bought += 1; } });
    const button = screen.getByRole("button", { name: /Buy for .*3,000.* \(one payment\)/ });
    button.click();
    expect(bought).toBe(1);
    expect(screen.queryByText(/upgrade/i)).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("button", { name: "Switch on" })).toBeNull();
  });
  it("tells someone who may not pay to ask the owner", () => {
    show({ unit: { ...sellable, can_buy: false } });
    expect(screen.getByText(/Ask the owner of the business to buy it/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Buy for/ })).toBeNull();
  });
  it("says not available, with a way to ask, when the platform does not sell it", () => {
    show({ unit: { ...sellable, sale_state: "not_for_sale", sale_price: null, can_buy: false }, supportEmail: "help@example.test" });
    expect(screen.getByText("Not available.")).toBeTruthy();
    expect(screen.getByText(/Not included in your plan\./)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Ask us" }).getAttribute("href")).toContain("mailto:help@example.test");
    expect(screen.queryByText(/upgrade/i)).toBeNull();
  });
  it("shows a bought add-on as Bought with its date and receipt, ready to switch on", () => {
    show({ unit: { ...sellable, in_plan: true, can_enable: true, sale_state: "bought", bought_at: "2030-02-03T10:00:00Z", receipt_invoice_id: "inv-1" } });
    expect(screen.getByText("Bought")).toBeTruthy();
    expect(screen.getByText(/Bought on/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Receipt" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Switch on" }).hasAttribute("disabled")).toBe(false);
  });
  it("shows an add-on the vendor gave as included, with no receipt", () => {
    show({ unit: { ...sellable, in_plan: true, can_enable: true, sale_state: "bought", bought_free: true, bought_at: "2030-02-03T10:00:00Z", receipt_invoice_id: null } });
    expect(screen.getByText("Included for you")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Receipt" })).toBeNull();
  });
});
