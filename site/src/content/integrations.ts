import type { Lang } from "./types";
import type { AvailKey } from "./availability";

export type IconName = "chat" | "phone" | "blocks" | "book" | "receipt" | "bank" | "coins" | "sheet" | "code" | "bolt" | "till" | "boxes" | "truck" | "people" | "wallet" | "ledger" | "person" | "check" | "bell" | "thumb" | "plug";

export interface IntegrationCard {
  /** Page id of the detail page (null when there is none). */
  page: string;
  icon: IconName;
  name: string;
  /** What it does for the owner, in plain words. */
  title: string;
  text: string;
  chip: string;
  tone: "ok" | "info" | "warn";
  /** Optional small label, e.g. "Optional add-on". */
  extra?: string;
  /** Capability that depends on an outside service: while it is "soon" in availability.ts the card shows a Coming soon chip and its one-line note instead of this text. */
  avail?: AvailKey;
  /** Fragment on the detail page, e.g. "h-webhooks". */
  hash?: string;
}
export interface IntegrationGroup { id: string; h2: string; lead: string; cards: IntegrationCard[] }
export interface IntegrationsPage {
  note: string;
  groups: IntegrationGroup[];
  howH2: string;
  steps: { t: string; d: string }[];
  ctaH2: string;
  ctaText: string;
  ctaButton: string;
  listName: string;
}

/** The Integrations page as data. Plain words for owners; status chips follow docs/channels.md, connectors.md, public-api.md, webhooks.md. */
export const integrationsPage: Record<Lang, IntegrationsPage> = {
  en: {
    note: "Anything marked Coming soon is on its way. Tell us what you use and we will let you know when it opens.",
    groups: [
      {
        id: "messaging", h2: "Hear from Ziira on your phone",
        lead: "You should not have to open a screen to find out something is wrong. Ziira can come to you.",
        cards: [
          { page: "integrations-whatsapp", icon: "chat", name: "WhatsApp", title: "Get your daily summary and alerts on WhatsApp", text: "Each morning, a short note on how every branch did. If a till shows a suspicious refund, you hear about it that day. Tap Approve or Reject right in the chat.", chip: "Available", tone: "ok", extra: "Optional add-on", avail: "whatsapp" },
        ],
      },
      {
        id: "payments", h2: "Get paid on the phone, and know it",
        lead: "Customers pay with their phone. Ziira matches each payment to the right sale, so nothing goes missing. M-Pesa is the example for Kenya; other countries get their own add-on.",
        cards: [
          { page: "integrations-mpesa", icon: "phone", name: "M-Pesa", title: "Know a customer paid by M-Pesa without checking your phone", text: "The cashier asks the customer to pay on their phone. When the money arrives, the sale is marked paid and the payment is recorded against it.", chip: "Available", tone: "ok", extra: "Country add-on", avail: "mpesa" },
        ],
      },
      {
        id: "systems", h2: "Keep the system you already use",
        lead: "Changing software is painful. You do not have to. Ziira can watch the system you have, without changing anything in it, and tell you each day where money or stock does not add up.",
        cards: [
          { page: "intelligence-source-erpnext", icon: "blocks", name: "ERPNext", title: "Watch your ERPNext, without changing it", text: "Spot a cashier who voids sales, or stock that vanished, in the books you already keep.", chip: "View only", tone: "ok", avail: "erpnext" },
          { page: "intelligence-source-odoo", icon: "blocks", name: "Odoo", title: "Watch your Odoo, without changing it", text: "Ziira looks at your invoices, payments and stock each day and flags what looks wrong.", chip: "View only", tone: "ok", avail: "odoo" },
          { page: "intelligence-source-zoho-books", icon: "book", name: "Zoho Books", title: "Watch your Zoho Books, without changing it", text: "See customers who are late paying and supplier prices that crept up.", chip: "View only", tone: "ok", avail: "zoho-books" },
          { page: "intelligence-source-quickbooks", icon: "receipt", name: "QuickBooks Online", title: "Watch your QuickBooks Online, without changing it", text: "Get a daily check of sales, bills and payments, and a plain summary for the owner.", chip: "View only", tone: "ok", avail: "quickbooks" },
          { page: "intelligence-source-bank", icon: "bank", name: "Bank statements", title: "Check that the bank got what you sold", text: "Compare each day's sales with the money that actually reached the bank.", chip: "View only", tone: "ok" },
          { page: "intelligence-source-mobile-money", icon: "coins", name: "Mobile-money statements", title: "Match mobile-money payments to sales", text: "Find a payment with no sale, or a sale marked paid with no payment.", chip: "View only", tone: "ok" },
          { page: "intelligence-source-files", icon: "sheet", name: "CSV, Excel and PDF files", title: "No connection? Just upload your reports", text: "Save your sales and stock report from any till or accounting package and upload it. Ziira checks it the same way.", chip: "Upload files", tone: "info" },
        ],
      },
      {
        id: "developers", h2: "For your developer",
        lead: "If someone builds or maintains your website, shop app or reports, these let their tools work with Ziira.",
        cards: [
          { page: "integrations-api", icon: "code", name: "API", title: "Let another app talk to Ziira", text: "An API is a way for your developer or another app to read and add Ziira information, for example showing your stock on your website. You choose exactly what it may do.", chip: "Stable, versioned", tone: "info" },
          { page: "integrations-api", icon: "bolt", name: "Webhooks", title: "Tell another app the moment something happens", text: "A webhook is an automatic message sent when a sale, payment or low-stock alert happens, so your other systems stay up to date without anyone checking.", chip: "Signed messages", tone: "info", hash: "h-webhooks" },
        ],
      },
    ],
    howH2: "How it works, in three steps",
    steps: [
      { t: "Connect", d: "Switch on an add-on, or give Ziira permission to look at your system. Looking only, never changing." },
      { t: "Ziira does the work", d: "It checks your numbers every day, or sends you the alert or the payment request." },
      { t: "You stay in control", d: "Switch any connection off at any time, and it stops. You can also take back the permission on your side." },
    ],
    ctaH2: "Don't see yours? Tell us",
    ctaText: "Tell us which system, bank or service you use, and we will tell you how it can work.",
    ctaButton: "Tell us",
    listName: "Ziira integrations",
  },
};
