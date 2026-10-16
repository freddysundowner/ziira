/** Messaging channels plugin: set up how the business sends email and SMS, and send a test message. */
import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "messaging",
  routes: [{ path: "/messaging/channels", page: () => import("./pages/ChannelsPage"), permission: "settings.manage" }],
  menu: [{ label: "messaging:menu", to: "/messaging/channels", permission: "settings.manage", order: 20, area: "settings", section: "channels", icon: "settings" }],
  translations: { en, sw },
});
