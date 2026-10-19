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
};
const show = (props: { forEdition?: boolean; recommended?: boolean }) =>
  render(<MemoryRouter><UnitCardView unit={pack} all={[pack]} onEnable={() => undefined} onDisable={() => undefined} onRemove={() => undefined} {...props} /></MemoryRouter>);

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
