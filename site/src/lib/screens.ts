import type { ImageMetadata } from "astro";
import type { ScreenKey } from "../content/types";

const files = import.meta.glob("../assets/screens/*.webp", { eager: true, import: "default" }) as Record<string, ImageMetadata>;

export function screen(key: ScreenKey): ImageMetadata {
  const hit = Object.entries(files).find(([f]) => f.endsWith(`/${key}.webp`));
  if (!hit) throw new Error(`Missing screenshot src/assets/screens/${key}.webp (run make site-screens)`);
  return hit[1];
}

export const screenAlt: Record<"en", Record<ScreenKey, { alt: string; cap: string }>> = {
  en: {
    home: { alt: "The Ziira home screen with a getting-started checklist, shortcuts to each area and today's cash balance, for the demo business", cap: "The Ziira home screen (demo data)" },
    command: { alt: "The Ziira Command Center for a demo hardware business: 57 open items by severity, the most pressing ones with the amount involved and a next step, beside the grouped sidebar", cap: "Command Center: what needs attention, with the money involved and what to do next (demo data)" },
    findings: { alt: "The Findings list in Ziira: 57 open findings, the total amount involved and a filterable table ordered by severity", cap: "Findings, most important first (demo data)" },
    finding: { alt: "One Ziira finding, a cash close that ended KES 530 over, with its recommended action, the figures it is based on, its details and its history", cap: "A finding with its evidence, details and history (demo data)" },
    sales: { alt: "The Ziira Sales list for a demo business: receipt numbers with date, branch, cashier, total and a Posted or Voided status", cap: "Every sale with its cashier, branch and status (demo data)" },
    till: { alt: "The Ziira point-of-sale terminal: a grid of products with price and stock on the left and a sale with three items totalling KES 4,975 and a Pay button on the right", cap: "The till: pick products, see the total, take payment (demo data)" },
    stock: { alt: "The Ziira Stock page with On hand and Low stock tabs, branch and location filters and a table of products, locations and quantities", cap: "Stock on hand by product and location (demo data)" },
    orders: { alt: "The Ziira Purchase orders list: order number, supplier, order date, expected date, total and a Sent or Received status", cap: "Purchase orders: what you ordered and what is still to arrive (demo data)" },
    owing: { alt: "The Ziira Who owes us page: total owed, the overdue amount, customers owing, and a table of what each customer owes by how late it is", cap: "Who owes you, and how late it is (demo data)" },
    books: { alt: "The Ziira Financial reports page showing a profit and loss statement with income, cost of sales, gross profit and expenses", cap: "Profit and loss, straight from the books (demo data)" },
    payroll: { alt: "The Ziira Payroll page listing monthly payroll runs with period, pay date, employees, net pay and status", cap: "Payroll runs, one per pay period (demo data)" },
    connect: { alt: "The What Ziira can check panel of the Connected systems page, grouping checks into cash and sales, customers and credit, suppliers, stock, books and people, each showing which connections it needs", cap: "What Ziira can check, and which connection unlocks each check (demo data)" },
    "connect-add": { alt: "The Add a connection page: drop a bank or mobile-money statement or a sales, stock or expense file, or choose ERPNext, Odoo, QuickBooks Online or Zoho Books", cap: "Adding a connection: drop a statement, or choose your ERP (demo data)" },
    addons: { alt: "The Ziira Add-ons page with the business's edition, a list of what is switched on, and cards for each add-on with a Switch off button", cap: "Add-ons: switch parts of Ziira on or off (demo data)" },
    "intel-actions": { alt: "Ziira Settings, Intelligence actions tab: four levels from Report only to Routine actions by itself, with Level 1 selected, and a note that Ziira never moves money", cap: "Choose how far Intelligence may go: from report only to routine actions (demo data)" },
    brief: { alt: "The Ziira brief preview: a daily brief for the demo business listing yesterday's figures such as cash balance, stock value and overdue balances", cap: "A preview of the daily brief (demo data)" },
    "till-phone": { alt: "The Ziira till on a phone showing a sale of three items totalling KES 4,975 with a Pay button", cap: "The till on a phone (demo data)" },
    "command-phone": { alt: "The Ziira Command Center on a phone showing 57 open items and the most pressing finding first", cap: "Command Center on a phone (demo data)" },
  },
};
