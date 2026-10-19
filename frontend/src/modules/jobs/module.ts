import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import enGarage from "./i18n/en.garage.json";
import sw from "./i18n/sw.json";
import swGarage from "./i18n/sw.garage.json";

type Dict = { [key: string]: string | Dict };
/** The garage texts add to the base texts; where both have a group (such as "parts"), the keys are joined, not replaced. */
function join(base: Dict, extra: Dict): Dict {
  const out: Dict = { ...base };
  for (const [key, value] of Object.entries(extra)) {
    const have = out[key];
    out[key] = typeof value === "object" && typeof have === "object" ? join(have, value) : value;
  }
  return out;
}

const VIEW = "jobs.view";
const MANAGE = "jobs.manage";
const SETTINGS = "jobs.settings";

export default defineModule({
  unit: "jobs",
  requires: ["products"],
  routes: [
    { path: "/jobs", page: () => import("./pages/JobsPage"), permission: VIEW },
    { path: "/jobs/new", page: () => import("./pages/ReceivePage"), permission: MANAGE },
    { path: "/jobs/workshop", page: () => import("./pages/WorkshopPage"), permission: VIEW },
    { path: "/jobs/items", page: () => import("./pages/ItemsPage"), permission: VIEW },
    { path: "/jobs/items/:assetId", page: () => import("./pages/ItemPage"), permission: VIEW },
    { path: "/jobs/settings", page: () => import("./pages/SettingsPage"), permission: SETTINGS },
    { path: "/jobs/:jobId", page: () => import("./pages/JobPage"), permission: VIEW },
  ],
  menu: [
    { label: "jobs:menu.jobs", to: "/jobs", permission: VIEW, order: 20, area: "services", icon: "purchases", keywords: "jobs:keywords.jobs" },
    { label: "jobs:menu.workshop", to: "/jobs/workshop", under: "/jobs", permission: VIEW, order: 20.5, area: "services", icon: "boxes", keywords: "jobs:keywords.workshop" },
    { label: "jobs:menu.items", to: "/jobs/items", under: "/jobs", permission: VIEW, order: 21, area: "services", icon: "boxes", keywords: "jobs:keywords.items" },
    { label: "jobs:menu.settings", to: "/jobs/settings", permission: SETTINGS, order: 90, area: "services", icon: "settings", setup: true, keywords: "jobs:keywords.settings" },
  ],
  slots: {
    "dashboard.widgets": [{ label: "jobs:widget.title", component: () => import("./slots/ReadyWidget"), permission: VIEW, order: 31 }],
  },
  translations: { en: join(en, enGarage), sw: join(sw, swGarage) },
});
