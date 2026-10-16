import type { HelpJourney } from "./types";

export const journeys: HelpJourney[] = [
  { id: "get-started", n: 1, title: "Get started", blurb: "Create your account, set up your business, invite your team and take a tour.", description: "Create your Ziira account, choose what you need, set up your company and branches, invite your team and learn your way around the screens." },
  { id: "sell", n: 2, title: "Sell", blurb: "Products, opening stock, the till, payments, receipts, credit sales, returns and closing the day.", description: "Add products and prices, open a till, make and take payment for a sale, sell on credit, handle returns, sell offline and close the till." },
  { id: "stock", n: 3, title: "Stock", blurb: "Check stock levels, receive goods, adjust and count stock, move stock between branches.", description: "Check what you hold, receive goods, correct and count stock, and move stock between your branches and stores." },
  { id: "buy", n: 4, title: "Buy", blurb: "Suppliers, purchase orders, receiving goods, supplier bills and returns.", description: "Add suppliers, order goods, receive them, record and pay supplier bills and send goods back to a supplier." },
  { id: "customers", n: 5, title: "Customers and credit", blurb: "Customer records, credit limits, who owes you and sending reminders.", description: "Add customers, set credit limits, see who owes you money and remind them to pay." },
  { id: "money", n: 6, title: "Money", blurb: "Match payments, read reports, record expenses, reconcile the bank and close the month.", description: "Match payments to sales, read your reports, record expenses, reconcile your bank account and close the month." },
  { id: "people", n: 7, title: "People", blurb: "Employees, attendance, leave and payroll.", description: "Add employees, record attendance and leave, and run payroll." },
  { id: "intelligence", n: 8, title: "Ziira Intelligence", blurb: "Your daily brief, findings, suggested actions, Ask Ziira, alerts and connecting another system.", description: "Read your daily brief, work through findings, approve suggested actions, set your alerts and connect your existing system or a statement." },
  { id: "settings", n: 9, title: "Add-ons and settings", blurb: "Switch add-ons on and off, import your data, numbering, roles, security and notifications.", description: "Switch add-ons on and off, import data from spreadsheets, set document numbers, roles, two-step verification and notifications." },
  { id: "support", n: 10, title: "Help and support", blurb: "Fix common problems, find a word you do not know, and contact us.", description: "Fix common problems, look up unfamiliar words and find out how to contact the Ziira team." },
];
