// The full reference for Ziira Intelligence (/intelligence/complete-guide/): the optional detail behind the step-by-step page (pages/intel.en.ts). Plain words, short sentences.
// Every count (checks, actions, ask tools) comes from the generated catalogue (src/lib/catalog.ts): never type one here (tests/complete-guide.test.ts fails if you do).
// Every statement must be checkable against docs/intelligence.md, docs/ai.md, docs/standalone-mode.md, docs/connectors.md, docs/channels.md and the code.
import type { ScreenKey, Faq } from "./types";
import { catalog, totals, checkByCode, checkAnchor, n, AREA_NAMES } from "../lib/catalog";
import { availability, isSoon, soonKeys, type AvailKey } from "./availability";

/** A "Coming soon" note for capabilities held back in availability.ts (nothing when they are all available). */
const soonCallout = (keys: AvailKey[]): GBlock[] => (keys.some(isSoon) ? [{ t: "callout", tone: "info", title: "Coming soon", text: keys.filter(isSoon).map((k) => availability[k].note).join(" ") + " [Tell us](@get-started) and we will let you know when it opens." }] : []);
const tag = (k: AvailKey): string => (isSoon(k) ? " (coming soon)" : "");

export interface Pin { x: number; y: number }
export type GBlock =
  | { t: "p"; text: string[] }
  | { t: "ul" | "ol"; items: string[] }
  | { t: "h3"; text: string; id?: string }
  | { t: "table"; caption: string; head: string[]; rows: string[][] }
  | { t: "callout"; tone: "info" | "warn" | "ok"; title?: string; text: string }
  | { t: "shot"; key: ScreenKey; alt: string; caption: string; pins: Pin[]; legend: string[] }
  | { t: "diagram"; name: "pipeline" | "sources" | "normal" | "lifecycle" | "ladder" | "privacy"; label: string; caption: string }
  | { t: "timeline"; title: string; items: { time: string; title: string; text: string }[] }
  | { t: "steps"; items: { title: string; text: string; example: string }[] }
  | { t: "terms"; title: string; items: { term: string; def: string }[] }
  | { t: "stories"; items: Story[] }
  | { t: "split"; left: GBlock[]; right: GBlock[] }
  | { t: "catalog" } | { t: "actions" } | { t: "asktools" } | { t: "counts" };

export interface Story { id: string; kind: string; title: string; setup: string; finds: string[]; act: string; limit?: string }
export interface GSection { id: string; title: string; summary: string; blocks: GBlock[] }

const G = (code: string): string => checkByCode(code).title;
/** A link to a check in the catalogue, by code (fails the build if the check does not exist). */
const chk = (code: string): string => `[${G(code)}](#${checkAnchor(code)})`;
const T = totals;
const area = (k: string): number => T.by_area[k] ?? 0;
const group = (key: string) => catalog.groups.find((g) => g.key === key)!;

export const guideTitle = "Ziira Intelligence: the complete guide to daily business checks";

export const intro = {
  lead: "The detail behind the step-by-step page. Read what you need and skip the rest.",
  glance: [
    `${T.checks} checks, listed one by one, with an example of each`,
    "Where the data comes from",
    `${T.actions} actions it can suggest, and how much you let it do`,
    "What it cannot do, in plain words",
  ],
};

// ---------------------------------------------------------------------------------------------------------------------
const s1: GSection = {
  id: "idea", title: "What it does", summary: "Every day it checks your records and tells you what to look at.",
  blocks: [
    { t: "p", text: [
      "Intelligence reads your sales, stock, payments and books. It compares them with evidence that is hard to change, and with what is normal for you.",
      "Then it tells you the few things worth your time, most important first, with the records behind each one. New here? See [how it works in six steps](@intelligence-how).",
    ] },
    { t: "ul", items: [
      "**It looks.** It reads records. It does not watch people.",
      "**It asks.** A thing to look at is a question, not an accusation. Most have a good reason.",
      "**It shows proof.** Every one links to the records behind it.",
      "**It waits for you.** Nothing that touches money, prices, credit or stock changes without a person saying yes.",
    ] },
  ],
};

const s3: GSection = {
  id: "data", title: "Where the data comes from", summary: "Ziira itself, or the system you already use.",
  blocks: [
    { t: "p", text: [
      "**In Ziira:** it reads everything Ziira holds, live. This is the deepest mode.",
      "**On a system you keep:** Ziira reads it, keeps a copy, and runs checks on the copy. It never changes your system. In the app this is the Connected systems page.",
    ] },
    { t: "table", caption: "What each source gives", head: ["Source", "What Ziira reads", "How often", "What you give"], rows: [
      [`[ERPNext](@intelligence-source-erpnext)${tag("erpnext")}`, "Sales, invoices, payments, stock, expenses, journals, people, users", "Once a day", "A view-only user and key"],
      [`[Odoo](@intelligence-source-odoo)${tag("odoo")}`, "Sales, invoices, payments, stock, expenses, journals, people, users", "Once a day", "A view-only user and key"],
      [`[Zoho Books](@intelligence-source-zoho-books)${tag("zoho-books")}`, "Invoices, bills, payments, expenses, journals, contacts. No stock", "Once a day", "Your approval in the browser"],
      [`[QuickBooks Online](@intelligence-source-quickbooks)${tag("quickbooks")}`, "Sales, invoices, bills, payments, expenses, journals. No stock", "Once a day", "Your approval in the browser"],
      ["[Bank statement](@intelligence-source-bank)", "Money in and out", "When you upload one", "A PDF, Excel, CSV or photo"],
      ["[Mobile-money statement](@intelligence-source-mobile-money)", "Money in and out", "When you upload one", "A PDF, Excel, CSV or photo"],
      ["[Sales, stock or expense files](@intelligence-source-files)", "Whatever the file holds", "When you upload one", "An Excel or CSV export"],
    ] },
    { t: "ul", items: [
      "**Only complete days are judged.** A statement that ends early never makes a quiet day look bad.",
      "**Looking only.** Ziira sends requests to look, never to change. You give a separate user or approval, not your own login, and you can take it back at any time.",
      "**Uploaded files** are read, and their lines are kept. The file itself is not.",
    ] },
    { t: "shot", key: "connect", alt: "The What Ziira can check panel: checks grouped into cash and sales, customers and credit, suppliers, stock, books and people, each showing which connection it needs", caption: "What Ziira can check today, and what would switch more on (demo data).", pins: [{ x: 6, y: 22 }, { x: 47.5, y: 30 }, { x: 4.6, y: 34 }], legend: ["How much can run on what is connected today.", "One card per area.", "A padlock means a check is waiting for a connection."] },
    ...soonCallout(["erpnext", "odoo", "zoho-books", "quickbooks", "photo-statements"]),
  ],
};

const s4: GSection = {
  id: "checks", title: "What it checks", summary: `${T.checks} checks, one by one.`,
  blocks: [
    { t: "p", text: [
      `There are **${T.checks} checks**: **${T.ziira}** read Ziira's own records and **${T.connected}** read a system you connect. Each asks one plain question, and most have limits you can change.`,
      "The list is made from the software itself, so the numbers here are the numbers in the product. Open a check to see an example and its limits.",
    ] },
    { t: "counts" },
    { t: "catalog" },
    { t: "callout", tone: "info", title: "If both run, you hear once", text: "If Ziira and a connected system cover the same area at the same branch, the connected system's check stays quiet there." },
  ],
};

const s5: GSection = {
  id: "normal", title: "How it knows what is unusual", summary: "It learns your normal.",
  blocks: [
    { t: "split", left: [
      { t: "p", text: [
        "Some checks use a fixed limit, such as a customer being late after 30 days. Many questions have no fixed answer. Is 14 cancelled sales a lot? It depends on the cashier.",
        "So Ziira looks at your own last 90 days. For each cashier, branch, product and weekday, it works out the usual range. A figure is flagged only when it is well above that range.",
        `There are ${T.baselines} such measures, such as each cashier's share of cancelled sales, refunds and discounts.`,
      ] },
      { t: "ul", items: [
        "**It needs about two weeks of records** before it judges a measure.",
        "**Expect some wrong alerts in the first weeks.** They fade as you answer \"Not a problem\".",
        "**You set the limits.** Every check can be switched off or changed in What Ziira watches.",
      ] },
    ], right: [
      { t: "diagram", name: "normal", label: "A chart of daily cancelled sales for one cashier: most days inside a shaded normal band, one day far above it", caption: "Unusual means well outside your own usual range." },
    ] },
  ],
};

const s6: GSection = {
  id: "alerts", title: "Things to look at", summary: "What each one contains, who sees it, and how it ends.",
  blocks: [
    { t: "p", text: ["The same problem seen again updates the same item. You do not get copies."] },
    { t: "split", left: [
      { t: "ul", items: [
        "**What happened,** in one sentence.",
        "**How urgent:** urgent, soon or worth a look.",
        "**The money involved.** The biggest come first.",
        "**The proof:** the sales, bills or counts behind it.",
        "**What to do next.**",
        "**Where it came from:** Ziira, or your connected system.",
        "**Its history:** who did what, and when.",
      ] },
    ], right: [
      { t: "shot", key: "finding", alt: "One thing to look at, a cash close that ended over its limit, with its suggested next step, the figures it is based on, its details and its history", caption: "One thing to look at, with its proof (demo data).", pins: [{ x: 22, y: 15.5 }, { x: 41.7, y: 19.5 }, { x: 27, y: 50.5 }, { x: 81, y: 25.6 }], legend: ["How urgent it is, and its state.", "What you can do: I'm on it, Explain what happened, Fixed, Give to someone, Ask someone to explain, Remind me later, Not a problem.", "What to do next.", "The figures and records behind it."] },
    ] },
    { t: "p", text: ["People see the items for the branches their role covers. A branch manager sees their own branch, and not payroll."] },
    { t: "ul", items: [
      "**I'm on it, then Explain what happened.** A person writes what happened. It is saved with their name.",
      "**Give to someone,** or **Ask someone to explain**. They get a message and answer in the app.",
      "**Fixed,** or **Not a problem**. You can tell Ziira the whole kind of thing is normal at a branch, for a person or everywhere, for 30 days or always.",
      "**Remind me later** puts it aside. It comes back sooner if it gets worse.",
      "**Closes by itself** when a state clears, such as a product back in stock. It reopens if the problem returns.",
    ] },
  ],
};

const s7: GSection = {
  id: "briefs", title: "The daily summary and urgent alerts", summary: "What arrives, when, and how you avoid too many messages.",
  blocks: [
    { t: "split", left: [
      { t: "ul", items: [
        "**The summary** has your key figures against the day before, and the top things to look at for your role.",
        "**You choose the time,** daily or weekly, in your company's time zone.",
        "**Where:** in the app and by email. SMS and WhatsApp are add-ons. Each person chooses their own.",
        "Read [what a daily owner brief should contain](@guide-daily-owner-brief).",
      ] },
    ], right: [
      { t: "shot", key: "brief", alt: "A preview of the daily summary: yesterday's figures such as cash balance, stock value and overdue balances", caption: "A preview of the daily summary (demo data).", pins: [{ x: 33, y: 19 }, { x: 93, y: 24 }, { x: 34, y: 36.5 }], legend: ["Choose daily or weekly, and how it is sent.", "Send it to yourself now, or preview it.", "Yesterday's figures, each against the day before."] },
    ] },
    { t: "ul", items: [
      "**Urgent alerts are off until you switch a channel on.** Until then everything appears in the app.",
      "**You set the bar.** Only items at or above the level you choose go out at once. The rest wait for the summary.",
      "**Quiet hours** delay a message. They never drop it.",
      "**One message per problem.** The do-not-contact list is respected.",
    ] },
    ...soonCallout(["email", "sms", "whatsapp"]),
  ],
};

const s8: GSection = {
  id: "ask", title: "Ask Ziira, the AI helper", summary: "Optional. It writes sentences. It never makes up numbers.",
  blocks: [
    { t: "p", text: ["**It is off until an Owner agrees.** When on, it explains a thing to look at in plain sentences, puts the most urgent first, and answers your questions in English or Swahili. On WhatsApp it needs the WhatsApp add-on."] },
    { t: "diagram", name: "privacy", label: "Your question goes to Ziira, which looks up your own records with tools filtered to what you may see, names are replaced by labels, only then the model writes a sentence, and every number in it is checked against your records", caption: "How an answer is made and checked." },
    { t: "ul", items: [
      "**It changes nothing.** It can only read.",
      "**Numbers come from your records.** If a number in an explanation is not in the facts, the sentence is dropped and you keep the plain text. An answer with unchecked figures is marked.",
      "**It sees only what you may see.**",
      "**Consent:** an Owner agrees in Settings > AI assistant. Switching it off works at once.",
      "**Never sent:** phone numbers, emails, tax numbers, bank details, ID numbers or salaries. Names are replaced by labels such as Customer A.",
      "**A monthly limit** caps its use, and every call is logged without its text.",
    ] },
    { t: "asktools" },
    ...soonCallout(["ai-helper"]),
  ],
};

const levelRows = [
  ["Watch", "Tells you. Changes nothing.", "The daily summary and alerts", "Anyone can read"],
  ["Ask", "Lets a manager ask a named person to explain.", "\"Please explain Saturday at Branch C\"", "Someone who manages these items"],
  ["Prepare", "Prepares drafts for a person to approve.", "A draft purchase request", "Owner turns it on; the right person approves each one"],
  ["Act for me", "Runs routine jobs that move no money, under your rules.", "A reminder to customers over 30 days late", "Owner only"],
];

const s9: GSection = {
  id: "actions", title: "How much Ziira does for you", summary: `Watch, Ask, Prepare, Act for me. All ${T.actions} actions, listed.`,
  blocks: [
    { t: "p", text: ["Every business starts at Watch. Moving up is your choice. Each level includes the ones before it."] },
    { t: "table", caption: "The four levels", head: ["Level", "What Ziira does", "Example", "Who decides"], rows: levelRows },
    { t: "p", text: [
      `There are **${T.actions} actions**. **${T.automatic_actions}** are routine messages that move no money, so they can run by themselves under a rule you set. The others always need a person: ${catalog.actions.filter((a) => !a.automatic).map((a) => a.title.toLowerCase()).join(", ")}.`,
    ] },
    { t: "h3", text: "Every action" },
    { t: "actions" },
    { t: "h3", text: "Safety rules" },
    { t: "ul", items: [
      "**Ziira never moves money.** No action pays, refunds or transfers anything.",
      "**A person approves anything about money, prices, credit or stock.**",
      "**An action runs as the person who approved it,** with only their permissions.",
      "**Every action is recorded:** who approved it, and when.",
      "**Each automatic rule has a daily limit,** and only the Owner can create one.",
      "**A failed action is shown and not retried.**",
    ] },
    { t: "shot", key: "intel-actions", alt: "Settings, Intelligence actions: four levels from report only to routine actions, with the first selected, and a note that Ziira never moves money", caption: "You choose how far Ziira may go (demo data).", pins: [{ x: 42, y: 30.7 }, { x: 73, y: 55 }, { x: 68, y: 80 }], legend: ["The first level is where every business starts.", "The last level: routine jobs by themselves, under your rules.", "The promise: Ziira never moves money."] },
    { t: "p", text: ["With the WhatsApp add-on, a suggestion arrives with **Approve**, **Reject** and **Why?** buttons. A tap from a verified number counts as that person. Without the add-on, suggestions wait in the app. See [WhatsApp](@integrations-whatsapp)."] },
  ],
};

const s10: GSection = {
  id: "control", title: "Who controls what", summary: "Roles and settings.",
  blocks: [
    { t: "table", caption: "What each person can change", head: ["Setting", "Who"], rows: [
      ["Switch a check off, change its limits", "Owner, Finance Manager"],
      ["Raise the level to Prepare or Act for me", "Owner only"],
      ["Lower the level", "Whoever manages settings"],
      ["Automatic rules: create, edit, switch on", "Owner only. Anyone who manages these items can pause one"],
      ["AI helper on or off, monthly limit", "Owner only"],
      ["Your own summary time, channel and quiet hours", "Each person, for themselves"],
    ] },
    { t: "p", text: ["Every change, every step on an item, every action and every AI call is recorded. The record cannot be edited or deleted. See [roles and security](@help-roles-and-security)."] },
  ],
};

const s11: GSection = {
  id: "compare", title: "On Ziira, or on your existing system", summary: "What changes, and how to move later.",
  blocks: [
    { t: "ul", items: [
      "**In Ziira:** live, every part of the business, all four levels.",
      "**On your existing system:** daily or when you upload, only what the source records, Watch and Ask.",
    ] },
    { t: "p", text: ["If you move to Ziira later, the **Move to Ziira** tool carries over products, customers, suppliers, opening stock and what is owed, from what Ziira has already read. It shows a preview first, and you can undo the opening balances. Nothing is deleted automatically. See [connect your system](@help-connect-your-system)."] },
    { t: "p", text: ["While both run, the old system's check for that area stays quiet at that branch. The app asks whether to pause the old connection or keep both."] },
  ],
};

const stories: Story[] = [
  {
    id: "shop", kind: "A shop with tills", title: "A hardware shop with two tills, run in Ziira",
    setup: "The owner is out in the afternoon. A cashier and a storekeeper handle money and stock.",
    finds: [chk("pos.cashier_void_rate"), chk("pos.out_of_hours_sales"), chk("pos.till_cash_variance"), chk("inventory.out_of_stock")],
    act: "The owner asks the manager to explain the cancelled sales. She marks the out-of-hours sales Not a problem, because stock arrived after closing.",
  },
  {
    id: "existing", kind: "An accounting package plus statements", title: "A business that keeps its accounting package",
    setup: "No move planned. The owner connected the package and uploads the mobile-money statement every Monday.",
    finds: [chk("standalone.sale_without_payment"), chk("standalone.cash_deposit_gap"), chk("standalone.unmatched_receipt"), chk("standalone.duplicate_supplier_invoice")],
    act: "She reads the summary and asks the manager to explain. Drafts and automatic jobs need Ziira's own records.",
    limit: "A till export with no voids or discounts cannot show cashier habits.",
  },
];

const s12: GSection = {
  id: "stories", title: "Two example businesses", summary: "Made-up, not customers.",
  blocks: [
    { t: "stories", items: stories },
  ],
};

const s13: GSection = {
  id: "trust", title: "What protects you, and the limits", summary: "Your data, your control, and what it cannot do.",
  blocks: [
    { t: "ul", items: [
      "**Your data stays yours.** Every business has its own database and its own login.",
      "**Looking only.** On anything you connect, Ziira can only look, and you can take access back at any time.",
      "**Each person sees what their role covers.** A branch manager does not see payroll.",
      "**Records that stay put.** The history of who did what cannot be edited or deleted.",
      "**Stored keys are encrypted.** They are never shown again.",
      "**Privacy tools** find, export and anonymise a person's data on request. See [security and privacy](@security).",
    ] },
    { t: "ul", items: [
      "**It cannot see what is never recorded.** If staff do not record a sale, no check can see it.",
      "**It shows gaps. It does not prove wrongdoing.** Some alerts will be wrong, mostly in the first weeks.",
      "**It does not replace an accountant,** auditor or tax adviser.",
      "**Matching a payment to a sale** uses the payment code, or else the amount and time. It is not always one to one.",
      "**A scanned statement** needs your review before anything from it is saved.",
    ] },
    ...(soonKeys().length ? [{ t: "h3" as const, text: "Coming next" }, { t: "ul" as const, items: soonKeys().filter((k) => k !== "subscription-payments").map((k) => `**${availability[k].name}:** ${availability[k].note}`) }] : []),
  ],
};

export const faq: Faq[] = [
  { q: "Is it spying on my staff?", a: "No. It reads business records such as sales, stock and payments. It does not use cameras or tracking. A thing to look at is a question, not an accusation, and your staff's explanation is saved." },
  { q: "Can it be wrong?", a: "Yes, especially in the first weeks. Mark it Not a problem and it is not raised again. You can change any limit or switch a check off." },
  { q: "Does it work offline?", a: "The till keeps selling offline and sends each sale once when the internet returns. Intelligence checks those sales once they arrive. You need a connection to read your items." },
  { q: "What does the AI cost?", a: "The AI helper is optional and off until an Owner agrees. A monthly limit caps it and every call is logged. See [pricing](@pricing) for what your plan includes." },
  { q: "Can I turn it off?", a: "Yes. Switch off one check, turn off urgent alerts, switch off the AI, go back to Watch, or disconnect a system." },
  { q: "Does it work with my country's tax and payments?", a: "Currency, tax codes, payroll rules and phone codes are entered by your business. Services specific to a country are added separately." },
  { q: "How long until it is useful?", a: "Checks with a fixed limit, such as late customers, work on day one. Checks against your normal need about two weeks of records. When you connect a system, Ziira reads the past months first." },
  { q: "Do I have to replace my system?", a: "No. Ziira can watch Odoo, ERPNext, Zoho Books, QuickBooks Online, statements and exports without changing them. See [using it with your existing system](@intelligence-existing)." },
  { q: "Who sees the items?", a: "People whose role covers that branch. Payroll items reach only people allowed to see payroll." },
  { q: "Will it change my records, prices or stock?", a: "No, unless you allow it. Every business starts at Watch. At higher levels a person approves each change, and only routine messages can run by themselves. Ziira never moves money." },
  { q: "Will it message my customers by itself?", a: "Only at Act for me, with a payment-reminder rule you set. It sends up to a daily limit and skips anyone who asked not to be contacted." },
  { q: "Is my data used to train the AI?", a: "The agreement says data sent through the AI service is not used to train its models. Names are replaced with labels, and contact details and salaries are never sent." },
];

export const sections: GSection[] = [s1, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12, s13];
export const faqSection = { id: "faq", title: "Questions people ask", summary: `${faq.length} short answers.` };
export const allTitles = [...sections.map((s) => s.title), faqSection.title];
void AREA_NAMES; void area; void group; void n; void group;

/** Words on the page (prose, FAQ, definitions and the catalogue text), for the reading time and the TechArticle's wordCount. */
export function guideWords(prose = false): number {
  const reference = prose ? [] : [catalog.checks.map((c) => [c.title, c.plain, c.example]), catalog.actions.map((a) => [a.title, a.plain, a.example])];
  const text = JSON.stringify([sections, faq, ...reference]);
  return text.replace(/"(t|key|name|tone|id|kind|code)":"[^"]*"/g, " ").replace(/[^A-Za-z0-9' ]+/g, " ").split(/\s+/).filter(Boolean).length;
}
