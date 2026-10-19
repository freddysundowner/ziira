/** WhatsApp and SMS through Lead Intel: connect the business's WhatsApp number, manage message templates, read replies. */
import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "leadsintel",
  routes: [{ path: "/leadsintel/whatsapp", page: () => import("./pages/WhatsAppPage"), permission: "settings.manage" }],
  menu: [{ label: "leadsintel:menu", to: "/leadsintel/whatsapp", permission: "settings.manage", order: 30, area: "settings", section: "channels", under: "/admin/notifications", icon: "settings" }],
  translations: { en, sw },
});
