import type { MenuItem, PageRoute } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

/** The selling screen. The back office adds these to the POS module and places the translations under the key `terminal` of the `pos` namespace. */
export const terminalRoutes: PageRoute[] = [
  { path: "/pos/terminal", page: () => import("./pages/TerminalPage"), permission: "sales.sell" },
];

export const terminalMenu: MenuItem[] = [
  { label: "pos:terminal.menu", to: "/pos/terminal", permission: "sales.sell", order: 1, group: "sell", icon: "sales" },
];

export const terminalTranslations: { en: Record<string, unknown>; sw: Record<string, unknown> } = { en, sw };
