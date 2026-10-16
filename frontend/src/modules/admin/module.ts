/** The kernel's own screens: users, roles, settings, approvals, exceptions, notifications, API keys, privacy requests, support access and my account. Always active (unit "kernel"). */
import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import { ADDONS_OLD_PATHS, ADDONS_PATH } from "./paths";
import enAi from "./i18n/en.ai.json";
import enApps from "./i18n/en.apps.json";
import enBilling from "./i18n/en.billing.json";
import enChannels from "./i18n/en.channels.json";
import enIntegrations from "./i18n/en.integrations.json";
import enMore from "./i18n/en.admin.json";
import enOrg from "./i18n/en.org.json";
import sw from "./i18n/sw.json";
import swAi from "./i18n/sw.ai.json";
import swApps from "./i18n/sw.apps.json";
import swBilling from "./i18n/sw.billing.json";
import swChannels from "./i18n/sw.channels.json";
import swIntegrations from "./i18n/sw.integrations.json";
import swMore from "./i18n/sw.admin.json";
import swOrg from "./i18n/sw.org.json";

export default defineModule({
  unit: "kernel",
  routes: [
    { path: "/admin/users", page: () => import("./pages/UsersPage"), permission: "users.manage" },
    { path: "/admin/organisation", page: () => import("./pages/OrganisationPage"), permission: "organisation.manage" },
    { path: ADDONS_PATH, page: () => import("./pages/AppsPage"), permission: "units.manage" },
    // Earlier addresses of the page (it was Apps & plugins in Settings, then Features): old links and bookmarks still work.
    ...ADDONS_OLD_PATHS.map((path) => ({ path, page: () => import("./pages/AppsRedirect"), permission: "units.manage", tab: ADDONS_PATH })),
    { path: "/admin/roles", page: () => import("./pages/RolesPage"), permission: "roles.manage" },
    { path: "/admin/settings", page: () => import("./pages/SettingsPage"), permission: "settings.manage" },
    { path: "/admin/approvals", page: () => import("./pages/ApprovalsPage"), permission: "approvals.decide" },
    { path: "/admin/approval-rules", page: () => import("./pages/ApprovalRulesPage"), permission: "approvals.manage" },
    { path: "/admin/exceptions", page: () => import("./pages/ExceptionsPage"), permission: "exceptions.manage" },
    { path: "/admin/notifications", page: () => import("./pages/NotificationsPage"), permission: "settings.manage" },
    { path: "/admin/api-keys", page: () => import("./pages/ApiKeysPage"), permission: "api_keys.manage" },
    { path: "/admin/webhooks", page: () => import("./pages/WebhooksPage"), permission: "webhooks.manage" },
    { path: "/admin/privacy", page: () => import("./pages/PrivacyPage"), permission: "privacy.manage" },
    { path: "/admin/privacy/:requestId", page: () => import("./pages/PrivacyRequestPage"), permission: "privacy.manage" },
    { path: "/admin/support", page: () => import("./pages/SupportAccessPage"), permission: "support.grant" },
    { path: "/admin/billing", page: () => import("./pages/BillingPage"), permission: "billing.manage" },
    // Every signed-in user may open their own account page, so it names no permission.
    { path: "/admin/account", page: () => import("./pages/AccountPage"), anySignedIn: true },
  ],
  menu: [
    { label: "kernel:approvals", to: "/admin/approvals", permission: "approvals.decide", order: 40, area: "waiting", icon: "document", keywords: "nav.waitingKeywords" },
    { label: "kernel:exceptions", to: "/admin/exceptions", permission: "exceptions.manage", order: 41, area: "waiting", under: "/admin/approvals", icon: "security", keywords: "nav.waitingKeywords" },
    { label: "kernel:org.menu", to: "/admin/organisation", permission: "organisation.manage", order: 10, area: "settings", section: "business", icon: "settings" },
    { label: "kernel:settings", tab: "nav.tabs.general", to: "/admin/settings", permission: "settings.manage", order: 11, area: "settings", section: "business", icon: "settings" },
    { label: "kernel:users", to: "/admin/users", permission: "users.manage", order: 10, area: "settings", section: "access", icon: "people" },
    { label: "kernel:roles", to: "/admin/roles", permission: "roles.manage", order: 11, area: "settings", section: "access", icon: "security" },
    { label: "kernel:approvalRules", to: "/admin/approval-rules", permission: "approvals.manage", order: 12, area: "settings", section: "access", icon: "document" },
    { label: "kernel:notifications", to: "/admin/notifications", permission: "settings.manage", order: 10, area: "settings", section: "channels", icon: "document" },
    { label: "kernel:apiKeys", to: "/admin/api-keys", permission: "api_keys.manage", order: 40, area: "settings", section: "channels", icon: "security" },
    { label: "kernel:webhooks.menu", to: "/admin/webhooks", permission: "webhooks.manage", order: 41, area: "settings", section: "channels", icon: "security" },
    { label: "kernel:privacy", to: "/admin/privacy", permission: "privacy.manage", order: 10, area: "settings", section: "data", icon: "security" },
    { label: "kernel:supportAccess", to: "/admin/support", permission: "support.grant", order: 20, area: "settings", section: "data", icon: "security" },
    { label: "nav.areas.addons", keywords: "kernel:apps.keywords", to: ADDONS_PATH, permission: "units.manage", order: 10, area: "addons", icon: "boxes" },
    { label: "kernel:billing.menu", to: "/admin/billing", permission: "billing.manage", order: 20, area: "settings", section: "platform", icon: "finance" },
    // Opened from the account menu in the top bar, so it is not in the sidebar.
    { label: "kernel:myAccount", to: "/admin/account", order: 99, hidden: true, icon: "settings" },
  ],
  slots: {
    "shell.background": [{ component: () => import("./slots/WaitingBadge") }],
    "dashboard.widgets": [
      { component: () => import("./slots/BillingBannerWidget"), permission: "billing.manage", order: 1 },
      { label: "kernel:widgetApprovalsTitle", component: () => import("./slots/ApprovalsWidget"), permission: "approvals.decide", order: 5 },
      { label: "kernel:widgetExceptionsTitle", component: () => import("./slots/ExceptionsWidget"), permission: "exceptions.manage", order: 6 },
    ],
  },
  translations: { en: { ...en, ...enMore, ...enOrg, ...enAi, ...enApps, ...enChannels, ...enIntegrations, ...enBilling }, sw: { ...sw, ...swMore, ...swOrg, ...swAi, ...swApps, ...swChannels, ...swIntegrations, ...swBilling } },
});
