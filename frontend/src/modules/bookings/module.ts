import { defineModule } from "@/sdk";

import en from "./i18n/en.json";
import enDesk from "./i18n/en.desk.json";
import enOps from "./i18n/en.ops.json";
import sw from "./i18n/sw.json";
import swDesk from "./i18n/sw.desk.json";
import swOps from "./i18n/sw.ops.json";

const VIEW = "bookings.view";
const SETUP = "bookings.setup";
const CHECKOUT = "bookings.checkout";
const REPORTS = "bookings.reports";

export default defineModule({
  unit: "bookings",
  requires: ["products"],
  routes: [
    { path: "/calendar", page: () => import("./pages/CalendarPage"), permission: VIEW },
    { path: "/appointments", page: () => import("./pages/AppointmentsPage"), permission: VIEW },
    { path: "/waitlist", page: () => import("./pages/WaitlistPage"), permission: VIEW },
    { path: "/classes", page: () => import("./pages/ClassesPage"), permission: VIEW },
    { path: "/front-desk", page: () => import("./pages/FrontDeskPage"), permission: VIEW },
    { path: "/front-desk/bills", page: () => import("./pages/BillsPage"), permission: CHECKOUT },
    { path: "/recalls", page: () => import("./pages/RecallsPage"), permission: VIEW },
    { path: "/checkout/:checkoutId", page: () => import("./pages/CheckoutPage"), permission: CHECKOUT, tab: "/front-desk" },
    { path: "/staff-pay", page: () => import("./pages/StaffPayPage"), permission: REPORTS },
    { path: "/day-end", page: () => import("./pages/DayEndPage"), permission: REPORTS },
    { path: "/booking/resources", page: () => import("./pages/ResourcesPage"), permission: VIEW },
    { path: "/booking/services", page: () => import("./pages/ServicesPage"), permission: VIEW },
    { path: "/booking/rota", page: () => import("./pages/RotaPage"), permission: VIEW },
    { path: "/booking/settings", page: () => import("./pages/BookingSettingsPage"), permission: VIEW },
  ],
  menu: [
    { label: "bookings:calendar.title", to: "/calendar", permission: VIEW, order: 10, area: "services", icon: "calendar", keywords: "bookings:keywords.calendar" },
    { label: "bookings:appointments.title", to: "/appointments", under: "/calendar", permission: VIEW, order: 11, area: "services", icon: "document", keywords: "bookings:keywords.appointments" },
    { label: "bookings:classes.title", to: "/classes", under: "/calendar", permission: VIEW, order: 12, area: "services", icon: "people", keywords: "bookings:keywords.classes" },
    { label: "bookings:waitlist.title", to: "/waitlist", under: "/calendar", permission: VIEW, order: 13, area: "services", icon: "customers", keywords: "bookings:keywords.waitlist" },
    { label: "bookings:frontDesk.title", to: "/front-desk", permission: VIEW, order: 14, area: "services", icon: "bell", keywords: "bookings:keywords.frontDesk" },
    { label: "bookings:bills.title", to: "/front-desk/bills", under: "/front-desk", permission: CHECKOUT, order: 15, area: "services", icon: "receipt", keywords: "bookings:keywords.bills" },
    { label: "bookings:recalls.title", to: "/recalls", under: "/front-desk", permission: VIEW, order: 16, area: "services", icon: "customers", keywords: "bookings:keywords.recalls" },
    { label: "bookings:staffPay.title", to: "/staff-pay", permission: REPORTS, order: 60, area: "services", icon: "cash", keywords: "bookings:keywords.staffPay" },
    { label: "bookings:dayEnd.title", to: "/day-end", under: "/staff-pay", permission: REPORTS, order: 61, area: "services", icon: "receipt", keywords: "bookings:keywords.dayEnd" },
    { label: "bookings:resources.title", to: "/booking/resources", permission: VIEW, order: 80, area: "services", icon: "people", setup: true, keywords: "bookings:keywords.resources" },
    { label: "bookings:offers.title", to: "/booking/services", under: "/booking/resources", permission: VIEW, order: 81, area: "services", icon: "products", setup: true, keywords: "bookings:keywords.offers" },
    { label: "bookings:rota.title", to: "/booking/rota", under: "/booking/resources", permission: VIEW, order: 82, area: "services", icon: "calendar", setup: true, keywords: "bookings:keywords.rota" },
    { label: "bookings:settings.menu", to: "/booking/settings", under: "/booking/resources", permission: SETUP, order: 83, area: "services", icon: "settings", setup: true, keywords: "bookings:keywords.settings" },
  ],
  slots: {
    "dashboard.widgets": [{ label: "bookings:widget.today", component: () => import("./slots/TodayWidget"), permission: VIEW, order: 30 }],
  },
  translations: {
    en: { ...en, ...enDesk, ...enOps },
    sw: { ...sw, ...swDesk, ...swOps },
  },
});
