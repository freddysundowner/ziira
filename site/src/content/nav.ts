import type { IconName } from "./integrations";

/**
 * The site's navigation, in the words a shop or business owner uses. One list feeds the header menus and the footer.
 * A link names a page id (or a literal href); a link whose page does not exist is left out, so optional pages
 * (the Help centre) can come and go without breaking the menu.
 */
export interface NavLink { id?: string; href?: string; label: string; desc?: string; icon?: IconName; /** Tile colour 1-8 (see --t1..--t8 in global.css) */ color?: number }
export interface NavColumn { title?: string; links: NavLink[] }
export interface NavGroup {
  key: string;
  label: string;
  /** Page id or href the top-level label links to. */
  to: { id?: string; href?: string };
  mega?: boolean;
  right?: boolean;
  columns: NavColumn[];
  foot?: NavLink;
}

export const navGroups: NavGroup[] = [
  {
    key: "does", label: "What Ziira does", to: { id: "product" }, mega: true,
    columns: [
      { title: "Run the business", links: [
        { id: "core-pos", label: "Sales, tills and invoices", desc: "Counter sales and credit sales, even offline", icon: "till", color: 1 },
        { id: "core-purchasing", label: "Purchasing and suppliers", desc: "Order, receive, check the bill", icon: "truck", color: 3 },
        { id: "core-inventory", label: "Stock across branches", desc: "Counted, moved and valued", icon: "boxes", color: 2 },
        { id: "core-customers", label: "Customers and credit", desc: "Limits, statements, reminders", icon: "people", color: 4 },
      ] },
      { title: "Money and people", links: [
        { id: "core-payments", label: "Payments and matching", desc: "Which payments arrived, which did not", icon: "wallet", color: 6 },
        { id: "core-accounting", label: "Accounting and reports", desc: "Books that fill themselves as you work", icon: "ledger", color: 7 },
        { id: "core-people", label: "People and payroll", desc: "Staff, leave and pay with your rules", icon: "person", color: 5 },
      ] },
      { title: "Watch it for you", links: [
        { id: "intelligence-how", label: "Daily check: catch mistakes and losses", desc: "What looks wrong, with the proof", icon: "check", color: 8 },
        { id: "intelligence-complete", label: "Full reference for daily checks", desc: "Every check and option, in plain words", icon: "book", color: 6 },
        { id: "intelligence-existing", label: "Use it with the system you already have", desc: "Odoo, ERPNext, Zoho, QuickBooks, statements", icon: "plug", color: 2 },
        { id: "integrations", label: "Connect your tools", desc: "WhatsApp, mobile money, your own apps", icon: "bell", color: 3 },
      ] },
    ],
    foot: { id: "product", label: "See everything Ziira does →" },
  },
  {
    key: "who", label: "Who it is for", to: { id: "solutions-retail" },
    columns: [{ links: [
      { id: "solutions-retail", label: "Shops and retail", desc: "Hardware, agrovets, pharmacies, mini-marts", icon: "till" },
      { id: "solutions-distribution", label: "Wholesale and distribution", desc: "Buy in volume, sell on credit safely", icon: "truck" },
      { id: "solutions-multi-branch", label: "Businesses with several branches", desc: "See every branch without being there", icon: "blocks" },
    ] }],
  },
  {
    key: "how", label: "How it works", to: { href: "/#how-it-works" }, right: true,
    columns: [{ links: [
      { id: "get-started", label: "1. Create your business", desc: "Sign up, choose what you need", icon: "bolt" },
      { id: "intelligence-existing", label: "2. Bring in your data", desc: "Start fresh, or connect what you use", icon: "plug", color: 2 },
      { id: "intelligence-how", label: "3. Get your daily check", desc: "Alerts and a short summary each day", icon: "bell" },
    ] }],
    foot: { id: "help", label: "Questions? Visit the Help centre →" },
  },
  { key: "pricing", label: "Pricing", to: { id: "pricing" }, columns: [] },
  {
    key: "help", label: "Help", to: { id: "help" }, right: true,
    columns: [{ links: [
      { id: "help", label: "Help centre", desc: "Step-by-step answers", icon: "book" },
      { id: "guides", label: "Articles", desc: "Practical guides for owners", icon: "sheet" },
      { id: "glossary", label: "Words explained", desc: "ERP, POS, shrinkage and more", icon: "chat" },
      { id: "security", label: "Is my data safe?", desc: "What is protected, stated plainly", icon: "check" },
      { id: "get-started", label: "Talk to us", desc: "Tell us about your business", icon: "phone" },
    ] }],
  },
];

/** The app launcher: every capability as a coloured tile (home page and footer-free). Two-word labels. */
export interface AppTile { id: string; label: string; desc: string; icon: IconName; color: number }
export const appTiles: AppTile[] = [
  { id: "core-pos", label: "Sales", desc: "Tills, quotes, invoices, returns", icon: "till", color: 1 },
  { id: "core-purchasing", label: "Purchasing", desc: "Orders, goods in, supplier bills", icon: "truck", color: 3 },
  { id: "core-inventory", label: "Stock", desc: "Every branch, counted and moved", icon: "boxes", color: 2 },
  { id: "core-accounting", label: "Accounting", desc: "Books that fill themselves, and reports", icon: "ledger", color: 7 },
  { id: "core-people", label: "People and payroll", desc: "Staff, leave and pay", icon: "person", color: 5 },
  { id: "core-customers", label: "Customers", desc: "Credit, statements, reminders", icon: "people", color: 4 },
  { id: "core-payments", label: "Payments", desc: "Match money to sales", icon: "wallet", color: 6 },
  { id: "intelligence-how", label: "Intelligence", desc: "A daily check, with proof", icon: "bell", color: 8 },
  { id: "intelligence-existing", label: "Your systems", desc: "Watch Odoo, ERPNext, QuickBooks", icon: "plug", color: 2 },
  { id: "integrations", label: "Add-ons", desc: "WhatsApp, mobile money, API", icon: "blocks", color: 3 },
];
