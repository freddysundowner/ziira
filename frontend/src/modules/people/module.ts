import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import sw from "./i18n/sw.json";

export default defineModule({
  unit: "people",
  routes: [
    { path: "/employees", page: () => import("./pages/EmployeesPage"), permission: "employees.view" },
    { path: "/employees/:employeeId", page: () => import("./pages/EmployeePage"), permission: "employees.view" },
    { path: "/attendance", page: () => import("./pages/AttendancePage"), permission: "attendance.manage" },
    { path: "/leave", page: () => import("./pages/LeavePage"), permission: "employees.view" },
    { path: "/payroll", page: () => import("./pages/PayrollPage"), permission: "payroll.view" },
    { path: "/payroll/:runId", page: () => import("./pages/PayrollRunPage"), permission: "payroll.view" },
    { path: "/payslips/:payslipId", page: () => import("./pages/PayslipPage"), permission: "payroll.view" },
    { path: "/payroll-setup", page: () => import("./pages/PayrollSetupPage"), permission: "payroll.view" },
    { path: "/pay-components", page: () => import("./pages/PayComponentsPage"), permission: "employee.pay_edit" },
  ],
  menu: [
    { label: "people:menu.employees", to: "/employees", permission: "employees.view", order: 10, group: "people", icon: "people" },
    { label: "people:menu.attendance", to: "/attendance", permission: "attendance.manage", order: 11, group: "people", icon: "people" },
    { label: "people:menu.leave", to: "/leave", permission: "employees.view", order: 12, group: "people", icon: "people" },
    { label: "people:menu.payroll", to: "/payroll", permission: "payroll.view", order: 20, group: "people", icon: "payroll" },
    { label: "people:menu.setup", to: "/payroll-setup", permission: "payroll.view", order: 21, group: "people", icon: "settings" },
  ],
  slots: {
    "dashboard.widgets": [
      { label: "people:widget.title", component: () => import("./slots/PeopleWidget"), permission: "employees.view", order: 40 },
    ],
  },
  translations: { en, sw },
});
