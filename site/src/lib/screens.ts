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
    command: { alt: "The Ziira Today page for a demo hardware business: a sentence saying how many things need you, the most urgent things to look at as cards with Look into it, Give to someone, Not a problem and Remind me later, and an Ask Ziira box", cap: "Today: what needs you, most urgent first (demo data)" },
    findings: { alt: "The Things to look at page in Ziira: tabs for Open, Waiting for someone and Done, filters, and cards ordered by how urgent they are", cap: "Things to look at, most urgent first (demo data)" },
    finding: { alt: "One thing to look at in Ziira, supplier invoices that are overdue, with what we noticed, why it matters, what you can do next, the facts and what happened so far", cap: "A thing to look at, with the facts (demo data)" },
    sales: { alt: "The Ziira Sales list for a demo business: receipt numbers with date, branch, cashier, total and a Posted or Voided status", cap: "Every sale with its cashier, branch and status (demo data)" },
    till: { alt: "The Ziira point-of-sale terminal: a grid of products with price and stock on the left and a sale with three items totalling KES 4,975 and a Pay button on the right", cap: "The till: pick products, see the total, take payment (demo data)" },
    stock: { alt: "The Ziira Stock page with On hand and Low stock tabs, branch and location filters and a table of products, locations and quantities", cap: "Stock on hand by product and location (demo data)" },
    orders: { alt: "The Ziira Purchase orders list: order number, supplier, order date, expected date, total and a Sent or Received status", cap: "Purchase orders: what you ordered and what is still to arrive (demo data)" },
    owing: { alt: "The Ziira Who owes us page: total owed, the overdue amount, customers owing, and a table of what each customer owes by how late it is", cap: "Who owes you, and how late it is (demo data)" },
    books: { alt: "The Ziira Financial reports page showing a profit and loss statement with income, cost of sales, gross profit and expenses", cap: "Profit and loss, straight from the books (demo data)" },
    payroll: { alt: "The Ziira Payroll page listing monthly payroll runs with period, pay date, employees, net pay and status", cap: "Payroll runs, one per pay period (demo data)" },
    connect: { alt: "The What Ziira can check panel of the Connected systems page, grouping checks into cash and sales, customers and credit, suppliers, stock, books and people, each showing which connection it needs", cap: "What Ziira can check, and which connection switches each check on (demo data)" },
    "connect-add": { alt: "The Add a connection page: drop a bank or mobile-money statement or a sales, stock or expense file, or choose ERPNext, Odoo, QuickBooks Online or Zoho Books", cap: "Adding a connection: drop a statement, or choose your ERP (demo data)" },
    addons: { alt: "The Ziira Add-ons page with the business's edition, a list of what is switched on, and cards for each add-on with a Switch off button", cap: "Add-ons: switch parts of Ziira on or off (demo data)" },
    "intel-actions": { alt: "How much Ziira does for you: four steps called Watch, Ask, Prepare and Act for me, with Watch selected, and a note that Ziira never moves money", cap: "Choose how much Ziira does for you (demo data)" },
    brief: { alt: "The Daily summary page with a preview of the summary: yesterday's figures such as cash balance, stock value and overdue balances", cap: "A preview of the daily summary (demo data)" },
    "till-phone": { alt: "The Ziira till on a phone showing a sale of three items totalling KES 4,975 with a Pay button", cap: "The till on a phone (demo data)" },
    "command-phone": { alt: "The Ziira Today page on a phone showing how many things need you and the most urgent one first", cap: "Today on a phone (demo data)" },
  },
};
