// The complete guide to Ziira Intelligence (/intelligence/complete-guide/). Written for a business owner: plain words, every term explained once.
// Every count (checks, actions, ask tools) comes from the generated catalogue (src/lib/catalog.ts): never type one here (tests/complete-guide.test.ts fails if you do).
// Every statement must be checkable against docs/intelligence.md, docs/ai.md, docs/standalone-mode.md, docs/connectors.md, docs/channels.md and the code.
import type { ScreenKey, Faq } from "./types";
import { catalog, totals, checkByCode, checkAnchor, n, AREA_NAMES } from "../lib/catalog";

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
  lead: "Written for the owner, not the technician. Read it top to bottom in one sitting, or jump to the part you need. Every word that might be new is explained the first time it appears.",
  glance: [
    `${T.checks} checks, listed one by one, with an example of each`,
    "Where the data comes from: Ziira itself, or the system you already use",
    `${T.actions} actions it can suggest, and the four levels of control`,
    "What it cannot do, and what has not been tested yet",
  ],
};

// ---------------------------------------------------------------------------------------------------------------------
const s1: GSection = {
  id: "idea", title: "The idea in one minute", summary: "A careful accountant who reads every number, every night.",
  blocks: [
    { t: "split", left: [
      { t: "p", text: [
        "Imagine you hired a very careful accountant. Every night she reads every sale, every stock movement, every payment and every entry in your books. She knows what a normal Tuesday looks like at each branch, how many sales each cashier usually cancels, and which customers always pay late.",
        "Next morning she leaves one page on your desk: the few things worth your time, the most important first, with the papers that prove each one. She does not accuse anyone. She asks a question: \"Branch C sold half of its usual Saturday. Do you know why?\" If you agree, she can ask the manager for you. She never changes your books, your prices or your stock on her own.",
        "That is Ziira Intelligence, except it never gets tired, and it reads everything, every day.",
      ] },
    ], right: [
      { t: "callout", tone: "info", title: "In one sentence", text: "Every day, Ziira compares what your staff recorded with evidence that is hard to change, and with what is normal for your business, then tells you the most important things first." },
      { t: "ul", items: [
        "**It looks.** It reads records. It does not watch people.",
        "**It asks.** An alert is a question, not an accusation. Most have a good explanation.",
        "**It proves.** Every alert shows the records behind it.",
        "**It waits for you.** Nothing involving money, prices, credit or stock changes without a person saying yes.",
      ] },
    ] },
    { t: "timeline", title: "A day in the life (an example, with made-up figures)", items: [
      { time: "Overnight", title: "Ziira reads the day", text: "New sales, stock movements and payments are checked against what is normal. Checks run every six hours on their own." },
      { time: "07:00", title: "Your brief arrives", text: "A short summary: yesterday's figures against the day before, and three things to look at. You chose the time." },
      { time: "07:05", title: "You open the first alert", text: "\"Branch C sold 18,000 on Saturday. A normal Saturday there is about 52,000.\" The tills, the cashiers and the day are one tap away." },
      { time: "07:10", title: "You ask for an explanation", text: "You tap Ask someone to explain. The branch manager gets a message with the question." },
      { time: "10:30", title: "The answer comes back", text: "\"Power cut, the till was down for four hours.\" The answer is recorded with who gave it. You mark it Not a problem, with a reason." },
      { time: "14:00", title: "One urgent alert", text: "Only if you switched alerts on: a customer is 45 days late and has just been given more credit. It reaches the right people at once, outside the brief." },
      { time: "Evening", title: "A draft is prepared (level 3 only)", text: "Cement ran out at Branch A. Ziira drafts a purchase request and waits. Nothing is ordered until a person sends it." },
      { time: "Next night", title: "It keeps watching", text: "The closed alert does not come back. A new one appears only if something new happens." },
    ] },
  ],
};

const s2: GSection = {
  id: "how-it-works", title: "How it works, end to end", summary: "Seven steps from your records to a decision, and back.",
  blocks: [
    { t: "p", text: ["Everything Ziira Intelligence does follows one path. The picture shows it; the cards below explain each step with an example."] },
    { t: "diagram", name: "pipeline", label: "Seven steps: data in, compare with normal, alerts, brief, you decide, optional actions, keep learning", caption: "The path from your records to a decision, and back round again." },
    { t: "steps", items: [
      { title: "Data comes in", text: "Ziira reads the records it can see: its own tills, stock, books and payroll, and, if you use them, your other systems and statements.", example: "Yesterday's 214 sales, 31 stock movements and 12 bank lines are in." },
      { title: "Compare with what is normal", text: "Each check compares the records with a fixed limit you can set, with evidence that is hard to change (a payment on a statement), or with your own normal.", example: "Cashier B cancelled 14 sales. Their usual is one or two a day." },
      { title: "An alert is raised", text: "If the answer looks wrong, the check raises an alert with how serious it is, the money involved, a plain sentence, a suggested next step and the proof.", example: "\"Cashier B cancelled 14 sales after 9pm. Next step: ask the branch manager to explain.\"" },
      { title: "You get the brief, and urgent alerts", text: "A short summary arrives at the time you chose. Urgent things can reach you at once, if you switch that on.", example: "A brief at 07:00; a high-priority alert at 14:00." },
      { title: "You decide", text: "Look at the proof, ask someone to explain, give it to a person to deal with, or say it is not a problem. Your answer is recorded.", example: "You assign the alert to the branch manager." },
      { title: "Optional actions", text: "If you allow it, Ziira prepares a next step for a person to approve, and for routine things that move no money, can do it by itself under your rules.", example: "A draft purchase request for an out-of-stock product." },
      { title: "It keeps learning", text: "Your answers and your own history teach it what is normal for you, so the same thing is not raised twice and unusual means unusual for you.", example: "After a few weeks it knows that month-end Fridays are busy." },
    ] },
    { t: "split", left: [
      { t: "p", text: [
        "**Where AI fits.** Totals, gaps and comparisons are calculated directly from your records: no AI is involved, so the numbers cannot be invented. An optional AI helper only writes plain sentences and answers questions, and it is off until an Owner agrees (see [Ask Ziira](#ask)).",
        "**Where it runs.** Checks run on the Ziira server, not at the till. A shop can keep selling when the internet drops; Intelligence reads the sales once they arrive.",
      ] },
    ], right: [
      { t: "shot", key: "command", alt: "The Ziira Command Center for a demo hardware business: 57 open items by severity, and the most pressing ones with the money involved and a next step", caption: "The Command Center: what needs attention, most important first (demo data).", pins: [{ x: 24, y: 30 }, { x: 30, y: 35.5 }, { x: 22, y: 40.5 }, { x: 94, y: 24.5 }], legend: ["How many alerts are open, split by how serious they are.", "What happened, in one plain sentence, with the money involved.", "The suggested next step.", "See all alerts: the full list."] },
    ] },
  ],
};

const s3: GSection = {
  id: "data", title: "Where the data comes from", summary: "Ziira itself, or the system you already use. Always looking, never changing.",
  blocks: [
    { t: "h3", text: "Ziira itself" },
    { t: "p", text: ["When you run your business in Ziira, Intelligence reads everything Ziira holds: tills, stock, purchasing, customers and credit, payments, the books and payroll. It is live, it has the full detail (who did what, and when), and it can prepare actions in Ziira for approval. This is the deepest mode, because everything is already in one place."] },
    { t: "h3", text: "The system you already use" },
    { t: "p", text: ["You do not have to move. Ziira can read the system you keep, copy what it reads into a store of its own, and run the same kind of checks on the copy. This is called **standalone mode**; in the app it is the Connected systems page. Here is what each source gives."] },
    { t: "diagram", name: "sources", label: "Sources on the left (your ERP, statements, files) flow through a read-only reader into Ziira's own copy, then into checks and alerts", caption: "Standalone mode: Ziira reads, keeps a copy, and checks the copy. Your system is never written to." },
    { t: "table", caption: "What each source gives, and how fresh it is", head: ["Source", "What Ziira reads", "How fresh", "What you give"], rows: [
      ["[ERPNext](@intelligence-source-erpnext)", "Sales, invoices, payments, stock movements, expenses, journals, parties, users", "Read once a day by default (you can ask for more often)", "A limited, view-only key"],
      ["[Odoo](@intelligence-source-odoo)", "Sales, invoices, payments, stock movements, expenses, journals, parties, users", "Read once a day by default", "A view-only user and key"],
      ["[Zoho Books](@intelligence-source-zoho-books)", "Invoices, bills, payments, expenses, journals, contacts, items, users. No stock", "Read once a day by default", "Your approval, in the browser"],
      ["[QuickBooks Online](@intelligence-source-quickbooks)", "Sales, invoices, bills, payments, expenses, journals, customers, vendors, items. No stock", "Read once a day by default", "Your approval, in the browser"],
      ["[Bank statement](@intelligence-source-bank)", "Money in and out, with its reference, time and account", "When you upload one", "A PDF, Excel or CSV, or a photo"],
      ["[Mobile-money statement](@intelligence-source-mobile-money)", "Money in and out, with its code, time and payer", "When you upload one", "A PDF, Excel or CSV, or a photo"],
      ["[Sales, invoices, stock or expense files](@intelligence-source-files)", "Whatever the file holds: sales by cashier and branch, invoices and bills, stock movements, expenses", "When you upload one", "An Excel or CSV export from your till or software"],
    ] },
    { t: "h3", text: "What each source can and cannot check" },
    { t: "p", text: ["Coverage depends on what the source records. \"Full\" means the area is covered deeply; \"Some\" means only the checks that need that data run; a dash means that source gives nothing for the area."] },
    { t: "table", caption: "Coverage by area and source", head: ["Area", "Ziira itself", "ERP (ERPNext, Odoo)", "Accounting package (Zoho Books, QuickBooks Online)", "Statements (bank, mobile money)", "Files (sales, invoices, stock, expenses)"], rows: [
      ["Cash and sales", "Full: tills, daily closes, cash, card and mobile money", "Some: sales checked against the payments the ERP holds", "Some: sales and invoices against payments", "Some: money received and cash deposited, compared with sales", "Some: a sales file shows cashier and branch habits"],
      ["Customers and credit", "Full: limits, ageing, slower payers", "Some: late customers, credit to a late customer, slower payers", "Some: the same, from invoices", "-", "Some: an invoices file"],
      ["Suppliers and purchasing", "Full: price rises, margin squeeze, duplicates, bank changes, unreceived goods", "Some: price rises, duplicate bills and payments", "Some: duplicate bills and payments (no stock, so no price history)", "Some: the same payment sent twice", "Some: an invoices or a stock file"],
      ["Stock", "Full: levels, counts, expiry, transfers, losses", "Some: stock movements, losses, negative stock", "- (stock is not read)", "-", "Some: a stock movements file"],
      ["Books", "Full: journals, closed months, reconciliations", "Some: hand-made journals and expenses", "Some: hand-made journals and expenses", "Some: money received that matches nothing", "Some: an expenses file"],
      ["People and payroll", "Full: pay changes, overtime, attendance, leave, payroll timing", "Some: new users only", "Some: new users only", "-", "-"],
    ] },
    { t: "split", left: [
      { t: "h3", text: "How fresh is it?" },
      { t: "ul", items: [
        "**Ziira itself:** live. Checks run every six hours; the figures in the Command Center refresh every hour.",
        "**ERPs and accounting packages:** read on a schedule, once a day unless you change it, and never more often than every fifteen minutes.",
        "**Files and statements:** when you upload them. The newest file may overlap an older one; nothing is counted twice.",
        "**Only complete days are judged.** A statement that ends early never makes a quiet day look like a bad one.",
      ] },
      { t: "h3", text: "What \"read-only\" really guarantees" },
      { t: "ul", items: [
        "Ziira sends only requests to look. It never writes to, edits or deletes anything in your system.",
        "You give a dedicated key or approval, never a person's own login, and you can take it back in your system at any time. Ziira stops at once.",
        "Keys are stored encrypted, never shown again and kept out of logs. No password is ever shared.",
        "A file you upload is read and its lines kept for checking. The file itself is not kept.",
      ] },
    ], right: [
      { t: "shot", key: "connect-add", alt: "The Add a connection page: drop a bank or mobile-money statement or a sales, stock or expense file, or choose ERPNext, Odoo, QuickBooks Online or Zoho Books", caption: "Adding a connection: drop a statement, or choose your ERP (demo data).", pins: [{ x: 38, y: 38 }, { x: 36, y: 58 }, { x: 24, y: 68 }], legend: ["Drop a file here: PDF, photo, Excel or CSV. Ziira works out what it is.", "Or choose your ERP or accounting package.", "Each one says what it gives Ziira."] },
    ] },
    { t: "shot", key: "connect", alt: "The What Ziira can check panel: checks grouped into cash and sales, customers and credit, suppliers, stock, books and people, each showing which connection it needs", caption: "The Coverage panel shows, by area, what can be checked today and which connection would switch more on (demo data, so nothing is connected).", pins: [{ x: 5, y: 15 }, { x: 8, y: 24 }, { x: 10, y: 31 }], legend: ["How much of the catalogue can run on what is connected today.", "One card per area.", "A padlock means the check is waiting for a connection, and says which one."] },
    { t: "callout", tone: "warn", title: "Not yet tested on real accounts", text: "The four ERP and accounting connections were written from each vendor's public documentation and tested only against sample data. They have not been run against a real ERPNext, Odoo, Zoho Books or QuickBooks Online account. A first live run on a demo or test company comes first. Statement layouts were tested on constructed files; try a real statement from each bank before relying on it." },
  ],
};

const s4: GSection = {
  id: "checks", title: "What it checks", summary: `${T.checks} checks, one by one.`,
  blocks: [
    { t: "p", text: [
      `Intelligence has **${T.checks} checks** today: **${T.ziira}** that read Ziira's own records and **${T.connected}** that read a connected system. Each is a plain question with a limit you can change. The list below is the real list: it is produced from the software itself, so the numbers on this page are always the numbers in the product.`,
      "Open any check to see what it means, an example (made up), the limits you can change in plain words, and what data it needs. A check runs only if the part of Ziira it reads is switched on, and a check on a connected system runs only if that system supplies the data.",
    ] },
    { t: "counts" },
    { t: "catalog" },
    { t: "callout", tone: "info", title: "Some checks are twins", text: "Several checks exist twice, once for Ziira's own records and once for a connected system (for example the cashier habits and the late customer checks). They look at different data. If Ziira runs the same area at the same branch as a connected system, the connected check stays quiet there so you are never told the same thing twice (see [using it with Ziira or with your existing system](#compare))." },
  ],
};

const s5: GSection = {
  id: "normal", title: "How it knows what is unusual", summary: "Your normal, in plain words.",
  blocks: [
    { t: "split", left: [
      { t: "p", text: [
        "Some checks use a fixed limit you set: \"a customer is overdue after 30 days\". But many questions have no fixed answer. Is 14 cancelled sales a lot? For one cashier it is; for another, on payday, it is not. So Ziira learns **your normal**.",
        "For each cashier, branch, product and weekday it looks at your own last 90 days and works out the usual range. A figure is called **unusual** only when it is well outside that range: more than three times the usual swing above the average, and higher than all but the top 5 in every 100 normal days. That double test keeps one ordinary busy day from raising an alarm.",
        `There are ${T.baselines} such measures today, such as each cashier's share of cancelled sales, refunds and discounts, each branch's sales by weekday and each expense category.`,
      ] },
      { t: "ul", items: [
        "**It needs about two weeks of history** (at least 14 days of records) before it judges a measure at all. Until then that check stays quiet.",
        "**It relearns every week.**",
        "**Expect some wrong alerts in the first weeks.** They fade as Ziira learns, and as you say \"not a problem\".",
        "**You are in charge of the limits.** Every check has a switch, and its limits (how many days late counts as overdue, how big a discount is too big) can be changed in the app under Settings > Checks.",
      ] },
    ], right: [
      { t: "diagram", name: "normal", label: "A chart of daily cancelled sales for one cashier: most days inside a shaded normal band, one day far above it", caption: "Unusual means well outside your own usual range, not just \"a big number\"." },
    ] },
  ],
};

const s6: GSection = {
  id: "alerts", title: "Alerts (findings): what you get and what you can do", summary: "What an alert contains, who sees it, and how it ends.",
  blocks: [
    { t: "p", text: ["An alert (the app's word is **finding**) is the unit of work in Ziira Intelligence. The same problem seen again is the same alert, updated, so you do not get a pile of copies."] },
    { t: "split", left: [
      { t: "h3", text: "What an alert contains" },
      { t: "ul", items: [
        "**What happened,** in one plain sentence, in your currency.",
        "**How serious:** For information, Low, Medium, High or Critical.",
        "**The money involved,** used to rank alerts (the biggest first, within the same level).",
        "**The proof:** the exact records and figures behind it, linked, so you can open the sale, the bill or the count.",
        "**Where and when:** the branch, the period, when it was first noticed and last checked.",
        "**A suggested next step.**",
        "**Where it came from:** \"From Ziira\" or \"From your connected system\".",
        "**Its history:** every step, with who did it and when, including what someone explained.",
      ] },
    ], right: [
      { t: "shot", key: "finding", alt: "One Ziira finding, a cash close that ended over its limit, with its recommended action, the figures it is based on, its details and its history", caption: "One alert, with its proof and history (demo data).", pins: [{ x: 22, y: 21 }, { x: 63, y: 25 }, { x: 24, y: 31 }, { x: 24, y: 46 }, { x: 74, y: 31 }, { x: 24, y: 65 }], legend: ["How serious it is, its state, and its area.", "What you can do: I have seen this, Explain, Resolve, Assign, Ask someone to explain, Not a problem.", "What to do next.", "The figures and records it is based on.", "Amount, branch, period, who it is assigned to, and its source.", "History: who did what, and when."] },
    ] },
    { t: "h3", text: "Who sees which alert" },
    { t: "p", text: ["Alerts follow the same access rules as the rest of Ziira. An alert about one branch is seen by people whose role covers that branch; a company-wide alert by company-wide roles. A branch manager sees their own branch and not payroll. These are the default roles; a business can change them."] },
    { t: "table", caption: "Who sees and does what with alerts, by default", head: ["Role", "Sees alerts", "Can do"], rows: [
      ["Owner", "Everything", "Everything: acknowledge, explain, assign, resolve, say \"not a problem\", tune checks, set the action level"],
      ["Finance Manager", "Everything their role covers", "Acknowledge, assign, resolve, dismiss, ask someone to explain, tune checks"],
      ["Accountant", "What the owner allows", "Read the alerts and their explanations"],
      ["Branch Manager", "Their branch only", "Explain the alerts assigned to them"],
    ] },
    { t: "h3", text: "How an alert lives and ends" },
    { t: "diagram", name: "lifecycle", label: "An alert goes New, Seen, Explained, then Resolved or Not a problem; it can close by itself when the problem clears and can reopen if it comes back", caption: "The life of an alert." },
    { t: "ul", items: [
      "**New**, then **Sent** if it also went out as an urgent alert, then **Seen** when someone acknowledges it.",
      "**Explained:** a person (or the person you asked) writes what happened. The answer is stored with their name.",
      "**Assign** it to someone, or **Ask someone to explain** (level 2): they get a message and answer in the app.",
      "**Resolved** when dealt with, or **Not a problem** (a reason is required). A dismissed alert is not raised again.",
      "**Closes by itself** when the problem goes away, for checks about a state (a product is out of stock; a customer is overdue). Checks about an event that already happened (a cancelled sale on Tuesday) stay open until a person deals with them.",
      "**Reopens** if a resolved problem comes back.",
    ] },
    { t: "shot", key: "findings", alt: "The Findings list in Ziira: open findings, the total amount involved and a filterable table ordered by severity", caption: "The list of alerts: filter by status, severity, area, source and branch (demo data).", pins: [{ x: 24, y: 24 }, { x: 40, y: 35 }, { x: 22, y: 50 }, { x: 80, y: 47 }], legend: ["Open alerts, the amount involved, and how many are high or critical.", "Filters: status, severity, area, source, branch, and \"assigned to me\".", "One line each: what happened, where, and where it came from.", "The amount involved and how long it has been open."] },
  ],
};

const s7: GSection = {
  id: "briefs", title: "The daily brief and alerts", summary: "What arrives, when, and how you avoid being spammed.",
  blocks: [
    { t: "split", left: [
      { t: "h3", text: "The brief" },
      { t: "ul", items: [
        "**What is in it:** what happened (your key figures against the period before), and what needs attention (the top alerts for your role), in plain words.",
        "**When:** at the time you choose, in your company's time zone, daily and/or weekly. If the server was down at the time, the brief goes out later the same day.",
        "**Once a day:** a brief is sent once per day per kind. Briefs are stored so you can read them again.",
        "**Where:** in the app, by email, and with the optional add-ons, by SMS or WhatsApp. Each person chooses their own. Someone with no contact on file simply gets it in the app.",
        "Read [what a daily owner brief should contain](@guide-daily-owner-brief).",
      ] },
    ], right: [
      { t: "shot", key: "brief", alt: "The Ziira brief preview: a daily brief for the demo business listing yesterday's figures such as cash balance, stock value and overdue balances", caption: "A preview of the daily brief (demo data).", pins: [{ x: 47, y: 15 }, { x: 94, y: 24 }, { x: 24, y: 30.5 }, { x: 25, y: 38 }], legend: ["Choose daily or weekly, and how it is sent.", "Send it to yourself now, or show a preview.", "The brief's title and date.", "Yesterday's figures, each against the day before."] },
    ] },
    { t: "h3", text: "Urgent alerts" },
    { t: "ul", items: [
      "**Off by default.** Nothing is sent until the business turns a channel on. Until then, alerts and briefs appear in the app only.",
      "**You set the bar.** Only alerts at or above the severity you choose (High unless you change it) go out at once. Everything below waits for the brief.",
      "**To the right people only:** those whose role covers that alert's branch.",
      "**Quiet hours.** Each person sets hours when nothing is sent. A message is delayed to the end of the quiet period, never dropped. A critical alert passes quiet hours only if that person allowed it.",
      "**Each person chooses their channel** for alerts, for briefs and for approvals: the app only, email, or an optional add-on such as SMS or WhatsApp.",
    ] },
    { t: "h3", text: "How you are not spammed" },
    { t: "ul", items: [
      "One alert per problem per person: the same problem seen again is the same alert and is not sent twice.",
      "Only serious alerts interrupt you; the rest wait for the brief.",
      "Quiet hours and the do-not-contact list are respected. Someone who opted out of a channel is reached on another or left alone.",
      "If one channel is unavailable, the next is tried instead and the first attempt is recorded. Nothing is dropped silently.",
      "Replies by chat are limited to 30 commands per 10 minutes per person.",
    ] },
    { t: "callout", tone: "warn", title: "Delivery has not been tested live", text: "Email, SMS and WhatsApp delivery were built from each provider's public documentation and tested against stand-ins, not against live accounts. The in-app brief and alerts work today. Test each channel with a real number before you rely on it." },
  ],
};

const s8: GSection = {
  id: "ask", title: "Ask Ziira, the AI helper", summary: "Optional. Writes sentences. Never invents numbers.",
  blocks: [
    { t: "p", text: [
      "Ask Ziira is an optional layer. **It is off for every business until an Owner agrees.** When it is on, a language model does three things, all with words and never with figures:",
    ] },
    { t: "ol", items: [
      "**Explains an alert** in two to four plain sentences, labelled \"AI-written\". The plain text is always there too.",
      "**Orders the most pressing alerts**, with a one-line reason each, for the Command Center and the brief.",
      "**Answers your questions** in English or Swahili (\"which branch sold least this week?\"), on screen, and, with the WhatsApp add-on, by WhatsApp.",
    ] },
    { t: "diagram", name: "privacy", label: "Your question goes to Ziira, which looks up your own records with tools filtered to what you may see, names are replaced by labels, only then the model writes a sentence, and every number in it is checked against your records", caption: "How an answer is made, and checked." },
    { t: "h3", text: "What it cannot do" },
    { t: "ul", items: [
      "**It changes nothing.** No tool it can use writes anything. Actions go through levels 3 and 4, with a person.",
      "**It cannot invent numbers.** Every number in an explanation must appear in the alert's own facts, or the sentence is thrown away and you keep the plain text. In an answer to a question, every number must come from your data or be a simple rounding, sum, share or count of it; otherwise the answer is kept but marked \"Some figures could not be verified against your data\".",
      "**It cannot see more than you can.** It answers using only the records the asker is allowed to see, in their branches. A branch manager gets their own branch.",
      "**It does not remember earlier questions;** each one stands alone.",
    ] },
    { t: "h3", text: "Privacy, consent and control" },
    { t: "ul", items: [
      "**Consent.** An Owner must read the text and agree on Settings > AI assistant. Who agreed, when, and the exact text are stored. Switching it off is immediate: every later call is refused.",
      "**What is sent:** the alert's summary, the figures and the labels of its records, or your question and the small results of the lookups. **Never sent:** phone numbers, email addresses, tax numbers, bank details, ID numbers, passwords, keys or salaries. Customers, suppliers and staff appear as labels such as \"Customer A\" and are turned back into names on your screen. A name you type yourself into a question is sent as you typed it.",
      `**A monthly limit.** Usage is capped (2,000,000 tokens a month per company unless you change it, a token being a small piece of a word). When it is used up, calls stop until next month or until the limit is raised.`,
      "**Every call is logged:** who asked, why, when, a fingerprint of what was sent, how big and how it ended, but never the text itself. Conversations are forgotten after 90 days and the log after 400.",
      "**Training:** the consent text says data sent to the provider is not used to train its models, and production calls are refused until the operator confirms those terms are in place with the provider.",
    ] },
    { t: "asktools" },
    { t: "h3", text: "Example questions" },
    { t: "ul", items: [
      "Which branch sold the least last week?",
      "Who owes us money, and which of it is late?",
      "How many sales were cancelled yesterday, and where?",
      "What are our best-selling products this month?",
      "Which products are below their reorder level?",
      "What do we owe suppliers, and what is due this week?",
      "What was our profit this month, and how does it compare with last month?",
      "Which alerts are open for the Westside branch?",
    ] },
    { t: "callout", tone: "warn", title: "Not tested against the live AI service", text: "The connection to the AI provider was written from its public documentation and tested against a scripted stand-in. Nothing has been sent to the live service yet, so the quality of real answers, including in Swahili, is unproven. The checks on every answer make a bad reply harmless; they do not make it good." },
  ],
};

const levelRows = [
  ["1 · Report only", "Tells you what it found. Changes nothing.", "The daily brief and alerts", "Anyone can read"],
  ["2 · Ask for an explanation", "Also lets a manager ask a named person to explain an alert.", "\"Please explain the Saturday sales at Branch C\"", "Someone allowed to manage alerts"],
  ["3 · Prepare", "Also prepares suggested actions for a person to approve.", "A draft purchase request, a new selling price", "Owner (to turn it on); the right person approves each one"],
  ["4 · Act within your limits", "Also lets routine actions that move no money run by themselves under your rules.", "A payment reminder to customers over 30 days late", "Owner only (to turn it on and set the rules)"],
];

const s9: GSection = {
  id: "actions", title: "The four levels of action", summary: `Report, ask, prepare, act. Every one of the ${T.actions} actions, listed.`,
  blocks: [
    { t: "p", text: ["Finding a problem is half the job. Ziira can also help with what to do next, but you decide how far it goes. **Every business starts at level 1, and moving up is its choice.**"] },
    { t: "diagram", name: "ladder", label: "Four steps going up: report only, ask for an explanation, prepare for approval, act within limits", caption: "Each level includes the ones below it." },
    { t: "table", caption: "The four levels", head: ["Level", "What Ziira does", "Example", "Who decides"], rows: levelRows },
    { t: "h3", text: "Every action Ziira can suggest or take today" },
    { t: "p", text: [
      `There are **${T.actions} actions**, listed below from the software itself. At level 3 or 4 Ziira offers them for alerts that match, and a person approves. **${T.automatic_actions}** of them are routine messages that move no money, so, at level 4 and only under a rule you set, they can run by themselves. The others always need a person: ${catalog.actions.filter((a) => !a.automatic).map((a) => a.title.toLowerCase()).join(", ")}.`,
    ] },
    { t: "actions" },
    { t: "h3", text: "The safety rules, in plain words" },
    { t: "ul", items: [
      "**Ziira never moves money.** There is no action that pays, refunds or transfers anything.",
      "**Nothing that involves money, prices, credit or stock changes without a person approving it.** A rule can only ever cover a routine message, and the software checks this again when it runs, so a rule written for a price or a credit limit is simply ignored.",
      "**Approvals use the approver's own permissions.** An action is carried out as the person who approved it, so everything that person could not do on their own is refused. A branch manager cannot approve another branch's suggestion.",
      "**You can edit before you approve,** and the facts are checked again at the moment of doing, because the world may have changed.",
      "**Everything is recorded** in the action log, the alert's history and the audit log: who approved, when, and by which route.",
      "**Daily caps.** Each automatic rule has a daily limit you set, counted in your time zone. One run looks at no more than 100 alerts and adds no more than 100 suggestions.",
      "**Owner-only rules.** Creating, editing, resuming or switching on an automatic rule needs the Owner. Anyone allowed to manage alerts can pause or switch a rule off: doing less is always allowed.",
      "**Failures are visible.** An automatic action that fails is recorded, shown in the exceptions inbox and never retried by itself. A turned-down suggestion is not made again, and a done one is not repeated for seven days.",
      "**It only asks people who can be reached.** Reminders need an alert channel set up and a person with a phone number or email on file, and they respect quiet hours and the do-not-contact list.",
    ] },
    { t: "split", left: [
      { t: "h3", text: "Approving by WhatsApp button" },
      { t: "p", text: ["With the optional WhatsApp add-on switched on, a suggestion reaches the people who can approve it as a message with **Approve**, **Reject** and **Why?** buttons. A tap from a verified number counts as that person, with their permissions, and goes through exactly the same approval as in the app. A number Ziira cannot match to exactly one active user gets no reply at all. Without the add-on, suggestions wait in the app (Findings > Actions). See [WhatsApp](@integrations-whatsapp). It has not been run against the live service."] },
      { t: "h3", text: "Not built yet" },
      { t: "ul", items: ["Approving by SMS or email reply.", "Approving leave and payroll requests by reply (only Intelligence's own suggestions can be answered).", "Rules that depend on the customer's group or the size of one invoice (a rule can use the branch and the amount only)."] },
    ], right: [
      { t: "shot", key: "intel-actions", alt: "Ziira Settings, Intelligence actions: four levels from Report only to Routine actions by itself, with level 1 selected, and a note that Ziira never moves money", caption: "Settings > Intelligence actions: you choose how far Ziira may go (demo data).", pins: [{ x: 39, y: 36 }, { x: 69, y: 45 }, { x: 40, y: 62 }, { x: 40, y: 72 }], legend: ["Level 1 is where every business starts.", "Level 4: routine actions by themselves, under your rules.", "The promise: Ziira never moves money.", "Automatic rules, and a note that they do nothing until level 4."] },
    ] },
  ],
};

const s10: GSection = {
  id: "control", title: "Who controls what", summary: "Roles, settings and the trail it leaves.",
  blocks: [
    { t: "table", caption: "What each person can change", head: ["Setting", "Where", "Who"], rows: [
      ["Switch a check off, change its limits", "Settings > Checks", "Owner, Finance Manager"],
      ["Alert channel and the lowest severity that is sent at once", "Company settings", "Whoever manages settings"],
      ["Your own brief time, channel and quiet hours", "Command Center > Briefs, My account > Notifications", "Each person, for themselves"],
      ["Action level (raising it to 3 or 4)", "Settings > Intelligence actions", "Owner only"],
      ["Action level (lowering it)", "Settings > Intelligence actions", "Whoever manages settings"],
      ["Automatic rules (create, edit, switch on)", "Settings > Intelligence actions", "Owner only; pausing or switching off by anyone who manages alerts"],
      ["AI helper on or off, monthly limit, call log", "Settings > AI assistant", "Owner only"],
      ["Who may ask Ziira questions", "Roles", "Owner, Finance Manager, Branch Manager and Accountant by default"],
      ["Your company's time zone (briefs and \"odd hours\" are read in it)", "Company settings", "Whoever manages settings"],
    ] },
    { t: "ul", items: [
      "**Who can dismiss an alert:** whoever manages alerts (Owner and Finance Manager by default), and always with a reason.",
      "**Branch managers** see their own branch and explain what is assigned to them. They cannot change a check or an action rule.",
      "**The audit trail.** Every change to a check, every alert step, every action and every AI call is recorded with who, when and (for changes by chat) which channel. The record cannot be edited or deleted.",
      "Read more in [roles and security](@help-roles-and-security) and the [Help centre guide to the action level](@help-choose-the-action-level).",
    ] },
  ],
};

const s11: GSection = {
  id: "compare", title: "Using it with Ziira, or on your existing system", summary: "What changes by source, and how to move later.",
  blocks: [
    { t: "table", caption: "Intelligence inside Ziira, and on a system you keep", head: ["", "Everything in Ziira", "Watching your existing system"], rows: [
      ["What it sees", "Every part of the business, live", "What the system, statement or file provides"],
      ["How fresh", "Live", "Daily, or when you upload"],
      ["Depth of checks", "Full, including who changed what", "Limited to what the source records"],
      ["Actions", "Levels 1 to 4", "Levels 1 and 2: report and ask for an explanation"],
      ["What you switch", "You move your tills and books", "Nothing"],
      ["Alerts say where they come from", "From Ziira", "From your connected system"],
    ] },
    { t: "h3", text: "Moving to Ziira later" },
    { t: "p", text: ["If you start by watching another system and later move to Ziira, the **Move to Ziira** tool does the carrying for you. It works from what Ziira has already read, so you do not retype anything."] },
    { t: "ol", items: [
      "**Preview.** It shows, kind by kind, what it found, what it would create, what already exists in Ziira and what it would leave out, with the reasons. Nothing is written yet.",
      "**Move.** It brings over products, customers, suppliers, opening stock (the running balance at your start date) and what customers and suppliers still owe. Every record goes through Ziira's normal import checks, so each batch reconciles. Nothing is created twice.",
      "**Undo.** The opening balances can be reversed, all together, with a reason, as long as none has been paid. Products, customers, suppliers and stock cannot be deleted in Ziira, so the move cannot take those back.",
      "**Pause the old connection** when you are ready. Nothing is ever deleted automatically.",
    ] },
    { t: "p", text: ["People who used the old system are counted, not copied: invite them to Ziira yourself. No password is ever copied. Details: the [guide to connecting a system](@help-connect-your-system) and the [coverage panel guide](@help-coverage-panel)."] },
    { t: "h3", text: "Overlap protection" },
    { t: "p", text: ["During a move you may run both for a while. When Ziira itself handles the same ground as a connected system at a branch (it sells there, keeps its stock, enters its supplier bills), the old system's check for that area **stays quiet for that branch**, and Ziira's own check speaks. The app shows a banner, \"Your business is being checked twice\", with two choices: **pause the old connection**, or **keep both**. Every alert says where it came from, so you always know which is which."] },
  ],
};

const stories: Story[] = [
  {
    id: "shop", kind: "A shop with tills", title: "A hardware shop with two tills, run in Ziira",
    setup: "The owner is in the shop in the morning and at the bank in the afternoon. A cashier and a storekeeper handle money and stock the rest of the day.",
    finds: [chk("pos.cashier_void_rate"), chk("pos.out_of_hours_sales"), chk("pos.till_cash_variance"), chk("inventory.out_of_stock")],
    act: "The owner asks the shop manager to explain the cancelled sales, then marks the out-of-hours sales as Not a problem because stock was received after closing. At level 3, a draft purchase request waits for her to send.",
  },
  {
    id: "wholesale", kind: "Wholesale with credit customers", title: "A distributor that sells to shops on credit",
    setup: "Most sales are on account. Cash is tight at month end, and one supplier keeps raising prices.",
    finds: [chk("pos.customer_overdue"), chk("pos.credit_to_overdue_customer"), chk("pos.customer_over_credit_limit"), chk("purchasing.supplier_price_rise"), chk("purchasing.margin_squeeze")],
    act: "At level 4, with a rule she set, a payment reminder goes to customers more than 30 days late, up to a daily limit: reminders are one of the routine actions that can run by themselves. Lowering a credit limit and a new selling price always wait for her approval.",
  },
  {
    id: "branches", kind: "A multi-branch business", title: "Five branches and an owner who cannot be in all of them",
    setup: "Each branch manager sees only their branch; the owner and the finance manager see all.",
    finds: [chk("pos.branch_sales_low"), chk("inventory.transfer_not_received"), chk("inventory.shrinkage_rate"), chk("inventory.unusual_stock_moves"), chk("controls.new_wide_access")],
    act: "The owner reads one brief for the whole business. A manager sees only the alerts about their own branch and explains the ones assigned to them. The finance manager follows up the transfer that never arrived.",
  },
  {
    id: "existing", kind: "Only an ERP or QuickBooks, plus statements", title: "A business that keeps its accounting package and uploads mobile-money statements",
    setup: "No move planned. The owner connected the accounting package (read-only) and uploads the mobile-money statement every Monday.",
    finds: [chk("standalone.sale_without_payment"), chk("standalone.cash_deposit_gap"), chk("standalone.unmatched_receipt"), chk("standalone.duplicate_supplier_invoice"), chk("standalone.customer_overdue")],
    act: "Levels 1 and 2 only: the owner reads the brief and asks the manager to explain. Prepared and automatic actions need Ziira's own records.",
    limit: "What can be checked depends on what the source records. A till export with no voids or discounts cannot show cashier habits, and negative stock needs the stock history from the start.",
  },
];

const s12: GSection = {
  id: "stories", title: "Four example businesses", summary: "Made-up scenarios, not customers.",
  blocks: [
    { t: "callout", tone: "info", title: "These are examples", text: "The businesses and figures below are invented to show how the checks fit together. They are not customers or case studies. Each check named is a real one: click it to read its entry." },
    { t: "stories", items: stories },
  ],
};

const s13: GSection = {
  id: "trust", title: "Privacy, security and honesty", summary: "What is yours, what is promised, and what is not proven yet.",
  blocks: [
    { t: "split", left: [
      { t: "h3", text: "What you can rely on" },
      { t: "ul", items: [
        "**The data stays yours.** Your business is in control of what it connects. You can pause a connection, disconnect it, or disconnect and delete everything Ziira read from it.",
        "**Read-only on your other systems,** with a key you can withdraw at any time. A file you upload is not kept.",
        "**Consent for the AI.** Off until an Owner agrees, recorded, and revocable at once.",
        "**People only see what their role covers.** A branch manager does not see payroll.",
        "**Records that stay put.** The history of who did what cannot be edited or deleted.",
        "**Privacy tools:** Ziira can find, export and anonymise a person's data on request. Retention periods are your decision. See [security and privacy](@security).",
      ] },
    ], right: [
      { t: "h3", text: "What we do not claim" },
      { t: "ul", items: [
        "**No certifications.** We do not claim any.",
        "**No independent security test yet.** It is on our list before real customers; it has not been done.",
        "**No promise of catching everything.** It cannot see what is never recorded anywhere, it shows gaps rather than proving wrongdoing, and some alerts will be wrong, especially in the first weeks.",
        "**It does not replace an accountant,** auditor or tax adviser.",
      ] },
    ] },
    { t: "callout", tone: "warn", title: "Not tested against live services yet", text: "These were built from each provider's public documentation and tested against stand-ins, but never against a real account: **WhatsApp**, **SMS and email delivery**, **mobile-money payment requests**, the four **ERP and accounting connections** (ERPNext, Odoo, Zoho Books, QuickBooks Online) and **AI answers**. Reading a photo of a statement has no accuracy figure on real photos yet; every line read from a picture waits for you to confirm it. Try each on a test account before relying on it." },
    { t: "h3", text: "Current limits, plainly" },
    { t: "ul", items: [
      "Not every check works on every source: the coverage table above says which.",
      "Matching a payment to a sale uses the payment code, or else the amount and time. It is not always one-to-one, and works as well as your system records payment codes.",
      "A check about negative stock needs the stock history from the start, or an opening count.",
      "On another system, a pay or role *change* is not seen; only a new user is.",
      "A scanned statement needs review: digits are easy to misread, so nothing from a picture is stored until you confirm it.",
      "Ziira's own tills and the connected system's daily figures in the Command Center are not de-duplicated while both run.",
      "Alerts are only as good as the records. If staff do not record a sale, no check can see it.",
    ] },
  ],
};

const s14: GSection = {
  id: "ahead", title: "What is not built yet", summary: "Only what is written down. No dates, no promises.",
  blocks: [
    { t: "p", text: ["This list comes from our own notes. It is not a promise of when, or whether, any of it will arrive."] },
    { t: "ul", items: [
      "**Checks that need a record Ziira's other parts do not expose yet:** Ziira's own sales paid by mobile money or card with no matching payment, cash planning (bills due against upcoming payroll) and good customers who have gone quiet.",
      "**Tax and compliance checks,** such as invoices missing from a tax authority's system and statutory deadlines. The product specification lists them; they are not built.",
      "**Projects and assets** checks (work not invoiced, jobs over budget, vehicle costs). In the specification, not built.",
      "**Approving by SMS or email reply,** and approving leave and payroll requests by reply.",
      "**More connectors.** SAP Business One has no connector (it usually needs a partner). Older systems and some POS can use the file route.",
      "**Live tests** of the channels, the ERP connections and the AI service, listed above.",
    ] },
  ],
};

export const faq: Faq[] = [
  { q: "Is it spying on my staff?", a: "No. It reads business records (sales, stock, payments), not people: no cameras, no tracking, no messages. An alert is a question, not an accusation, and most have a good explanation. Ziira records the explanation, which protects honest staff as much as the business." },
  { q: "Can it be wrong?", a: "Yes. Expect some wrong alerts in the first weeks, until it has learned what is normal for you. You can say \"not a problem\" and it will not raise that one again, and you can change any limit or switch a check off. It also cannot see what is never recorded anywhere." },
  { q: "Does it work offline?", a: "Ziira's till keeps selling when the internet is down and sends each sale once when it is back. Intelligence runs on the server, so it checks those sales once they arrive, and you need a connection to read your alerts. On a connected system it works from the latest read or upload." },
  { q: "What does it cost to run the AI?", a: "The AI helper is optional and off until an Owner agrees. Its use is capped by a monthly limit that you can change (2,000,000 tokens a month per company unless you change it), and every call is logged. We do not state a price here: see [the pricing page](@pricing) for what your plan includes." },
  { q: "Can I turn it off?", a: "Yes, at several levels. Switch a single check off, turn off urgent alerts, switch the AI off (it stops at once), lower the action level to 1, or pause or disconnect a connected system. You can also disconnect and delete everything Ziira read from it." },
  { q: "Does it work with my country's tax and payments?", a: "Nothing about a country is built in. Currency, tax codes, payroll rules and phone codes are entered by your business. Services specific to a country, such as a mobile-money provider, are added separately, and tax-authority checks are not built yet." },
  { q: "How long until it is useful?", a: "Checks with a fixed limit, such as late customers or products out of stock, work from the first day. Checks that compare with your normal need about two weeks of history. When you connect a system or upload statements, Ziira reads the past months first, so it can start with some history." },
  { q: "Do I have to replace my current system?", a: "No. Ziira can watch Odoo, ERPNext, Zoho Books, QuickBooks Online, bank and mobile-money statements and spreadsheet exports without changing them, and you can move to Ziira later. See [using it with your existing system](@intelligence-existing)." },
  { q: "Who sees the alerts?", a: "People whose role covers that alert's branch. A branch manager sees their own branch, a finance manager sees the company, and payroll alerts reach only people allowed to see payroll. You choose the roles." },
  { q: "Will it change my records, prices or stock?", a: "Not unless you let it. Every business starts at reporting only. At higher levels a person approves each change, and only routine messages that move no money can run by themselves, under a rule only the Owner can set. Ziira never moves money." },
  { q: "Will it message my customers by itself?", a: "Only if you set the action level to 4 and make a rule for payment reminders. It then sends your usual reminder to customers who are late, up to a daily limit, and never to a customer who asked not to be contacted." },
  { q: "Is my data used to train the AI?", a: "The AI is off until an Owner agrees. The agreement states that data sent through the provider's service is not used to train its models, and Ziira refuses AI calls in production until the operator has those terms in place. Names are replaced with labels before anything is sent, and phone numbers, emails, tax numbers, bank details and salaries are never sent." },
  { q: "Can my accountant use it?", a: "Yes. The Accountant role can read alerts and their explanations, within what the owner allows, and ask Ziira questions. It does not replace an accountant: it gives them the exceptions to look at first." },
  { q: "How is this different from the reports in my ERP?", a: "Reports wait for someone to open them and look. Intelligence reads every record every day, compares today with your own normal, brings in the evidence that sits outside the ERP (mobile-money and bank statements), and tells the right person the important things first, with the proof." },
];

export const sections: GSection[] = [s1, s2, s3, s4, s5, s6, s7, s8, s9, s10, s11, s12, s13, s14];
export const faqSection = { id: "faq", title: "Questions people ask", summary: `${faq.length} honest answers.` };
export const allTitles = [...sections.map((s) => s.title), faqSection.title];
void AREA_NAMES; void area; void group; void n;

/** Words on the page (prose, FAQ, definitions and the catalogue text), for the reading time and the TechArticle's wordCount. */
export function guideWords(prose = false): number {
  const reference = prose ? [] : [catalog.checks.map((c) => [c.title, c.plain, c.example]), catalog.actions.map((a) => [a.title, a.plain, a.example])];
  const text = JSON.stringify([sections, faq, ...reference]);
  return text.replace(/"(t|key|name|tone|id|kind|code)":"[^"]*"/g, " ").replace(/[^A-Za-z0-9' ]+/g, " ").split(/\s+/).filter(Boolean).length;
}
