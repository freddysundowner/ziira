/** The kernel's own screens: users, roles, settings, approvals, exceptions, notifications, API keys and my account. Always active (unit "kernel"). */
import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import enMore from "./i18n/en.admin.json";
import sw from "./i18n/sw.json";
import swMore from "./i18n/sw.admin.json";

export default defineModule({
  unit: "kernel",
  routes: [
    { path: "/admin/users", page: () => import("./pages/UsersPage"), permission: "users.manage" },
    { path: "/admin/roles", page: () => import("./pages/RolesPage"), permission: "roles.manage" },
    { path: "/admin/settings", page: () => import("./pages/SettingsPage"), permission: "settings.manage" },
    { path: "/admin/approvals", page: () => import("./pages/ApprovalsPage"), permission: "approvals.decide" },
    { path: "/admin/approval-rules", page: () => import("./pages/ApprovalRulesPage"), permission: "approvals.manage" },
    { path: "/admin/exceptions", page: () => import("./pages/ExceptionsPage"), permission: "exceptions.manage" },
    { path: "/admin/notifications", page: () => import("./pages/NotificationsPage"), permission: "settings.manage" },
    { path: "/admin/api-keys", page: () => import("./pages/ApiKeysPage"), permission: "api_keys.manage" },
    // Every signed-in user may open their own account page, so it names no permission.
    { path: "/admin/account", page: () => import("./pages/AccountPage"), anySignedIn: true },
  ],
  menu: [
    { label: "kernel:approvals", to: "/admin/approvals", permission: "approvals.decide", order: 10, group: "admin", icon: "document" },
    { label: "kernel:exceptions", to: "/admin/exceptions", permission: "exceptions.manage", order: 11, group: "admin", icon: "security" },
    { label: "kernel:users", to: "/admin/users", permission: "users.manage", order: 90, group: "admin", icon: "people" },
    { label: "kernel:roles", to: "/admin/roles", permission: "roles.manage", order: 91, group: "admin", icon: "security" },
    { label: "kernel:settings", to: "/admin/settings", permission: "settings.manage", order: 92, group: "admin", icon: "settings" },
    { label: "kernel:approvalRules", to: "/admin/approval-rules", permission: "approvals.manage", order: 93, group: "admin", icon: "document" },
    { label: "kernel:notifications", to: "/admin/notifications", permission: "settings.manage", order: 94, group: "admin", icon: "document" },
    { label: "kernel:apiKeys", to: "/admin/api-keys", permission: "api_keys.manage", order: 95, group: "admin", icon: "security" },
    { label: "kernel:myAccount", to: "/admin/account", order: 99, group: "admin", icon: "settings" },
  ],
  slots: {
    "dashboard.widgets": [
      { label: "kernel:widgetApprovalsTitle", component: () => import("./slots/ApprovalsWidget"), permission: "approvals.decide", order: 5 },
      { label: "kernel:widgetExceptionsTitle", component: () => import("./slots/ExceptionsWidget"), permission: "exceptions.manage", order: 6 },
    ],
  },
  translations: { en: { ...en, ...enMore }, sw: { ...sw, ...swMore } },
});
