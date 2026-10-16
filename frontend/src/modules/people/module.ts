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
    { path: "/payslips/:payslipId", page: () => import("./pages/PayslipPage"), permission: "payroll.view", tab: "/payroll" },
    { path: "/payroll-setup", page: () => import("./pages/PayrollSetupPage"), permission: "payroll.view" },
    { path: "/pay-components", page: () => import("./pages/PayComponentsPage"), permission: "employee.pay_edit", tab: "/payroll-setup" },
  ],
  menu: [
    { label: "people:menu.employees", to: "/employees", permission: "employees.view", order: 10, area: "people", icon: "people" },
    { label: "people:menu.attendance", tab: "people:menu.attendanceLeave", to: "/attendance", permission: "attendance.manage", order: 20, area: "people", icon: "people" },
    { label: "people:menu.leave", to: "/leave", permission: "employees.view", order: 21, area: "people", under: "/attendance", icon: "people" },
    { label: "people:menu.payroll", to: "/payroll", permission: "payroll.view", order: 30, area: "people", icon: "payroll" },
    { label: "people:menu.setup", to: "/payroll-setup", permission: "payroll.view", order: 31, area: "people", under: "/payroll", icon: "settings" },
  ],
  slots: {
    "dashboard.widgets": [
      { label: "people:widget.title", component: () => import("./slots/PeopleWidget"), permission: "employees.view", order: 40 },
    ],
  },
  translations: { en, sw },
});
