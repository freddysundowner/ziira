/**
 * THE AVAILABILITY SWITCH. One entry per capability that depends on an outside service. Owner decision: all are "available" (copy is
 * normal present tense). To hold an item back, set it to "soon" and rebuild: its card and page then show a "Coming soon" chip with the one-line
 * note and a "Get notified" link, and pages that depend on it stop promising it. The owner's manual test list is docs/go-live-checklist.md (internal). Everything built and verified without outside services
 * (till, stock, purchasing, accounting, payroll, customers, the daily checks on Ziira's own data, the in-app summary, suggestions and
 * approvals, statements as CSV/Excel/PDF, reports, offline selling) is not listed here and is always presented as available.
 */
export type AvailKey =
  | "whatsapp" | "sms" | "email" | "mpesa" | "erpnext" | "odoo" | "zoho-books" | "quickbooks" | "ai-helper" | "photo-statements" | "subscription-payments";
export type Availability = "available" | "soon";
export interface AvailItem { status: Availability; /** What it will do, one customer-friendly line, shown while the item is "soon". */ note: string; /** Short name for lists. */ name: string }

export const availability: Record<AvailKey, AvailItem> = {
  whatsapp: { status: "available", name: "WhatsApp", note: "Your daily summary, urgent alerts and one-tap approvals on WhatsApp." },
  sms: { status: "available", name: "SMS", note: "Urgent alerts and customer reminders by text message." },
  email: { status: "available", name: "Email", note: "Your daily summary, alerts and customer reminders by email." },
  mpesa: { status: "available", name: "M-Pesa payments", note: "Customers pay with an M-Pesa prompt and the sale is marked paid for you." },
  erpnext: { status: "available", name: "ERPNext", note: "A daily check of the ERPNext you already use, view only." },
  odoo: { status: "available", name: "Odoo", note: "A daily check of the Odoo you already use, view only." },
  "zoho-books": { status: "available", name: "Zoho Books", note: "A daily check of the Zoho Books you already use, view only." },
  quickbooks: { status: "available", name: "QuickBooks Online", note: "A daily check of the QuickBooks Online you already use, view only." },
  "ai-helper": { status: "available", name: "Ask Ziira", note: "Ask questions in plain words and get written answers from your own records." },
  "photo-statements": { status: "available", name: "Photo statements", note: "Upload a photo of a paper statement and have it read for you." },
  "subscription-payments": { status: "available", name: "Online plan payments", note: "Pay for your Ziira plan online." },
};

export const isAvailable = (k: AvailKey): boolean => availability[k].status === "available";
export const isSoon = (k: AvailKey): boolean => !isAvailable(k);
export const soonKeys = (): AvailKey[] => (Object.keys(availability) as AvailKey[]).filter(isSoon);
/** Text to use only when the item is live; otherwise `otherwise` (empty by default). */
export const ifAvailable = (k: AvailKey, text: string, otherwise = ""): string => (isAvailable(k) ? text : otherwise);
/** The "Coming soon" line for a help guide status (empty when the item is available). */
export const soonStatus = (k: AvailKey): string => (isSoon(k) ? `Coming soon: ${availability[k].note}` : "");
/** What a card or page shows for an item: the normal copy when available, otherwise the chip and the one-line note. */
export function presentation(k: AvailKey): { soon: boolean; chip: string; note: string } {
  return isSoon(k) ? { soon: true, chip: "Coming soon", note: availability[k].note } : { soon: false, chip: "", note: availability[k].note };
}
