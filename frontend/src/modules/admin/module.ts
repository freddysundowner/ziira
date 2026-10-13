/** The kernel's own screens: users and roles. Always active (unit "kernel"). */
import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "kernel",
  routes: [
    { path: "/admin/users", page: () => import("./pages/UsersPage"), permission: "users.manage" },
    { path: "/admin/roles", page: () => import("./pages/RolesPage"), permission: "roles.manage" },
  ],
  menu: [
    { label: "kernel:users", to: "/admin/users", permission: "users.manage", order: 90 },
    { label: "kernel:roles", to: "/admin/roles", permission: "roles.manage", order: 91 },
  ],
  translations: { en, sw },
});
