// What to photograph for each Help guide picture. `key` matches src/content/help/*.ts. `marks` are the numbered circles, in the order of
// the guide's legend. ten: "demo" (default), "shop" (the scratch business) or "out" (signed out). pre(page) gets the page ready.
const exact = (t) => ({ exact: true });
export const T = (t) => (p) => p.getByText(t).first();
export const TX = (t) => (p) => p.getByText(t, { exact: true }).first();
export const B = (n) => (p) => p.getByRole("button", { name: n }).first();
export const BX = (n) => (p) => p.getByRole("button", { name: n, exact: true }).first();
export const TAB = (n) => (p) => p.getByRole("tab", { name: n }).or(p.getByRole("button", { name: n, exact: true })).or(p.getByRole("link", { name: n, exact: true })).first();
export const LB = (l) => (p) => p.getByLabel(l).first();
export const C = (css) => (p) => p.locator(css).first();
export const DLG = (css) => (p) => p.locator("[role=dialog]").locator(css).first();
export const H = (t) => (p) => p.getByRole("heading", { name: t }).first();

/** click something by its visible name: button, tab, link, menu item or plain text */
export const CL = (name, o = {}) => async (p) => {
  await p.getByRole("button", { name, exact: o.exact ?? true }).or(p.getByRole("tab", { name, exact: true })).or(p.getByRole("link", { name, exact: true })).or(p.getByRole("menuitem", { name, exact: true })).first().click();
  await p.waitForTimeout(o.wait ?? 900);
};
export const seq = (...fns) => async (p) => { for (const f of fns) await f(p); };
const choose = (label, text) => async (p) => {
  await p.getByText(label).first().click(); await p.waitForTimeout(400); await p.keyboard.type(text); await p.waitForTimeout(800);
  await p.getByRole("option").first().click().catch(async () => { await p.getByText(text).last().click(); }); await p.waitForTimeout(400);
};
const firstRow = async (p) => { await p.locator("main tbody tr").first().click(); await p.waitForTimeout(1300); };
/** the till keeps an unfinished sale in the browser: empty it first so each picture shows one item */
const clearCart = async (p) => { const c = p.getByRole("button", { name: "Clear", exact: true }); if (await c.count()) { await c.first().click().catch(() => {}); await p.waitForTimeout(300); const ok = p.locator("[role=dialog]").getByRole("button", { name: /Clear|Yes|Confirm/ }); if (await ok.count()) await ok.first().click(); } };
const addCement = async (p) => { await clearCart(p); await p.getByRole("button", { name: /Cement 50kg/ }).first().click(); await p.waitForTimeout(400); };

export const shots = [
  // ---- 1 Get started
  { key: "account-1-edition", ten: "out", url: "/register", marks: [C("label:has(input[type=radio])"), BX("Continue")] },
  { key: "account-2-business", ten: "out", url: "/register", pre: async (p) => {
      await p.getByText("Retail / POS").click(); await p.getByRole("button", { name: "Continue" }).click(); await p.waitForTimeout(500);
      await p.getByLabel("Your full name").fill("Demo Owner"); await p.getByLabel("Work email").fill("owner@example.test");
      await p.getByRole("button", { name: "Continue" }).click(); await p.waitForTimeout(600);
      for (const l of await p.locator("input[type=password]").all()) await l.fill("not-a-real-password-1");
      await p.getByRole("button", { name: "Continue" }).click(); await p.waitForTimeout(700);
      await p.getByLabel("Business name").fill("Mama Njeri Hardware"); await p.getByLabel("Country").click(); await p.keyboard.type("Kenya"); await p.getByRole("option", { name: /Kenya/ }).first().click(); await p.waitForTimeout(600);
    }, marks: [LB("Business name"), LB("Country"), BX("Continue")] },
  { key: "setup-1-organisation", ten: "shop", url: "/admin/organisation", marks: [B("Edit company"), B("Add branch"), (p) => p.getByRole("link", { name: "General", exact: true })] },
  { key: "team-1-users", ten: "shop", url: "/admin/users", marks: [B("New user"), BX("Actions")] },
  { key: "team-2-roles", ten: "shop", url: "/admin/users", pre: async (p) => { await p.getByRole("button", { name: "Actions" }).last().click(); await p.getByRole("menuitem", { name: "Roles and access" }).click(); await p.waitForTimeout(900); },
    marks: [DLG("select"), (p) => p.locator("[role=dialog] select").nth(1), DLG("button:has-text('Give role')")] },
  { key: "tour-1-home", url: "/", marks: [C("aside, nav"), TX("Search"), BX("Account"), T("Getting started")] },
  { key: "tour-2-account", url: "/", pre: CL("Account"), marks: [(p) => p.getByRole("menuitem", { name: "My account" }), (p) => p.getByRole("menuitem", { name: "Dark" }), (p) => p.getByRole("menuitem", { name: "Sign out" })] },

  { key: "fix-1-signin", ten: "out", url: "/", marks: [T("Forgot password?")], pad: 120 },
  { key: "support-1-access", url: "/admin/support", marks: [BX("Give support access")], pad: 120 },

  // ---- 2 Sell
  { key: "products-2-new", ten: "shop", url: "/products", pre: CL("New product"), marks: [LB("Name"), DLG("select >> nth=0"), BX("Save product")] },
  { key: "products-3-price", ten: "shop", url: "/products", pre: async (p) => { await p.getByText("Cement 50kg").first().click(); await p.waitForTimeout(900); await CL("Prices")(p); },
    marks: [C("select[aria-label='Price list']"), (p) => p.getByRole("textbox", { name: "Price" }), BX("Save price")] },
  { key: "opening-2-form", ten: "shop", url: "/stock/opening", marks: [(p) => p.locator("select").first(), T("Choose a product"), BX("Add a product"), BX("Post opening stock")] },
  { key: "sale-1-open", url: "/pos/terminal", marks: [LB("Branch"), LB("Till (device)"), LB("Opening float"), BX("Open till and start selling")], pad: 90 },
  { key: "sale-3-done", ten: "shop", url: "/pos/terminal", pre: async (p) => { await addCement(p); await p.getByRole("button", { name: /^Pay/ }).click(); await p.waitForTimeout(600); await p.getByLabel("Handed over").fill("1000"); await p.getByRole("button", { name: "Complete sale" }).click(); await p.waitForTimeout(2500); },
    marks: [T("Give change"), BX("New sale"), BX("Print receipt")], minH: 520 },
  { key: "pay-1-mobile", ten: "shop", url: "/pos/terminal", pre: async (p) => { await addCement(p); await p.getByRole("button", { name: /^Pay/ }).click(); await p.waitForTimeout(600); await p.getByRole("button", { name: "Mobile money", exact: true }).click(); await p.waitForTimeout(500); },
    marks: [DLG("button:has-text('Cash')"), (p) => p.getByLabel("Amount").first(), LB("Mobile money code"), BX("Complete sale")], minH: 560 },
  { key: "receipt-1-done", ten: "shop", url: "/pos/terminal", pre: async (p) => { await addCement(p); await p.getByRole("button", { name: /^Pay/ }).click(); await p.waitForTimeout(600); await p.getByRole("button", { name: "Complete sale" }).click(); await p.waitForTimeout(2500); },
    marks: [BX("Print receipt"), T("Thank you")], minH: 520 },
  { key: "receipt-2-reprint", ten: "shop", url: "/pos/sales", pre: firstRow, marks: [BX("Receipt"), BX("Return goods"), BX("Void sale")] },
  { key: "credit-1-limit", ten: "shop", url: "/customers", pre: async (p) => { await p.getByText("Wanjiku Builders").first().click(); await p.waitForTimeout(900); await CL("Credit")(p); await CL("Change credit")(p); await p.getByLabel(/^Credit limit/).fill("50000"); await p.getByLabel(/^Payment terms/).fill("14"); await p.locator("[role=dialog] textarea").fill("Regular builder, pays on time"); },
    marks: [LB("Credit limit"), LB("Payment terms"), DLG("textarea"), BX("Submit")] },
  { key: "credit-2-onaccount", ten: "shop", url: "/pos/terminal", pre: async (p) => { await addCement(p); await p.getByText("Walk-in customer").first().click(); await p.waitForTimeout(500); await p.getByRole("button", { name: /Wanjiku Builders/ }).click(); await p.waitForTimeout(500);
      await p.getByRole("button", { name: /^Pay/ }).click(); await p.waitForTimeout(600); await p.getByRole("button", { name: "Remove payment" }).first().click(); await p.getByRole("button", { name: "On account" }).click(); await p.waitForTimeout(400); },
    marks: [BX("On account"), (p) => p.getByLabel("Amount").first(), BX("Complete sale")], minH: 520 },
  { key: "quote-1-form", ten: "shop", url: "/pos/quotations/new", pre: seq(choose("Choose a customer", "Wanj"), choose("Choose a product", "Cem"), async (p) => { await p.getByLabel(/^Quantity/).first().fill("20"); }),
    marks: [T("Customer"), LB("Valid until"), H("Items"), BX("Save quotation")], minH: 480 },
  { key: "quote-2-deliver", ten: "shop", url: "/pos/orders", pre: async (p) => { await firstRow(p); await CL("Deliver")(p); }, marks: [LB("Deliver now"), LB("Goods leave from"), BX("Deliver and invoice")] },
  { key: "return-1-form", ten: "shop", url: "/pos/sales", pre: async (p) => { await firstRow(p); await CL("Return goods")(p); }, marks: [(p) => p.locator("[role=dialog] input").first(), LB("Reason"), LB("Refund as"), BX("Record return")] },
  { key: "offline-1-queue", ten: "shop", url: "/pos/terminal", marks: [B("Show sales waiting to be sent")], minH: 300, minW: 760 },
  { key: "close-1-till", ten: "shop", url: "/pos/tills", pre: firstRow, marks: [T("Expected cash"), H("Takings by method"), BX("Close till")], minH: 480 },
  { key: "close-2-count", ten: "shop", url: "/pos/tills", pre: async (p) => { await firstRow(p); await CL("Close till")(p); }, marks: [LB("Counted cash"), (p) => p.locator("[role=dialog]").getByRole("button", { name: "Close till" })] },

  // ---- 3 Stock
  { key: "levels-1-onhand", ten: "shop", url: "/stock", marks: [TAB("On hand"), C("select"), C("main tbody tr td:last-child")] },
  { key: "levels-2-movements", ten: "shop", url: "/stock/movements", marks: [(p) => p.getByRole("columnheader").first(), (p) => p.getByRole("columnheader").nth(2), (p) => p.getByRole("columnheader").last()] },
  { key: "receive-1-form", ten: "shop", url: "/receipts/new", pre: async (p) => { await p.getByRole("button", { name: "Add line" }).click(); await p.waitForTimeout(500); }, marks: [T("Choose a supplier"), LB("Delivery note no."), BX("Add line"), BX("Confirm and add to stock")], minH: 480 },
  { key: "adjust-1-form", ten: "shop", url: "/stock/adjustments", pre: async (p) => { await CL("New adjustment")(p); await p.locator("[role=dialog]").getByLabel("Reason").selectOption({ label: "Damaged" }).catch(() => {}); },
    marks: [(p) => p.locator("[role=dialog]").getByLabel("Location"), (p) => p.locator("[role=dialog]").getByLabel("Reason"), T("Choose a product"), BX("Save draft")] },
  { key: "adjust-2-count", ten: "shop", url: "/stock/counts", pre: firstRow, marks: [(p) => p.getByRole("columnheader", { name: "System" }), (p) => p.getByRole("columnheader", { name: "Counted" }), BX("Save counts"), BX("Finish counting")], minH: 420 },
  { key: "transfer-1-form", ten: "shop", url: "/stock/transfers", pre: CL("New transfer"), marks: [(p) => p.locator("[role=dialog] select").first(), T("Choose a product"), BX("Save draft")] },
  { key: "transfer-2-onway", ten: "shop", url: "/stock/transfers", pre: firstRow, marks: [(p) => p.getByText("On the way").first(), BX("Receive")] },

  // ---- 4 Buy
  { key: "supplier-1-new", ten: "shop", url: "/suppliers", pre: CL("New supplier"), marks: [DLG("input >> nth=0"), LB("Phone"), LB("Payment terms"), BX("Save")] },
  { key: "po-1-form", ten: "shop", url: "/orders/new", pre: seq(choose("Choose a supplier", "Sav"), choose("Choose a product", "Cem")), marks: [T("Savannah Cement"), LB("Deliver to"), BX("Add line"), BX("Save draft")], minH: 520 },
  { key: "grn-1-order", ten: "shop", url: "/orders", pre: async (p) => { await firstRow(p); const id = p.url().split("/").pop(); await p.goto(`${process.env.APP_URL ?? "http://localhost:5173"}/receipts/new?order=${id}`); await p.waitForLoadState("networkidle"); await p.waitForTimeout(1200); },
    marks: [LB("Delivery note no."), LB("Receive into"), LB("Quantity received"), BX("Confirm and add to stock")], minH: 480 },
  { key: "bill-1-form", ten: "shop", url: "/bills/new", pre: choose("Choose a supplier", "Sav"), marks: [T("Savannah Cement"), LB("Supplier's invoice no."), BX("Goods from a receipt"), BX("Save draft")], minH: 480 },
  { key: "bill-2-pay", ten: "shop", url: "/bills", pre: async (p) => { await firstRow(p); await CL("Pay")(p); }, marks: [LB("Amount"), LB("Method"), LB("Reference"), (p) => p.locator("[role=dialog]").getByRole("button", { name: "Pay", exact: true })] },
  { key: "sreturn-1-form", ten: "shop", url: "/receipts", pre: async (p) => { await firstRow(p); await CL("Return goods")(p); }, marks: [(p) => p.locator("[role=dialog] input").first(), LB("Reason for return"), BX("Send back")] },

  // ---- 5 Customers
  { key: "customer-1-new", ten: "shop", url: "/customers", pre: CL("New customer"), marks: [LB("Name"), LB("Phone"), LB("Customer group"), BX("Save")] },
  { key: "customer-2-page", url: "/customers", pre: firstRow, marks: [BX("Receive payment"), TAB("Details"), BX("Add contact")] },
  { key: "limit-1-tab", url: "/customers", pre: async (p) => { await firstRow(p); await CL("Credit")(p); }, marks: [T("Credit today"), BX("Change credit"), T("Credit history")] },
  { key: "owes-1-ageing", url: "/receivables", marks: [T("Total owed"), T("1-30 days"), (p) => p.locator("main tbody tr").first()], minH: 480 },
  { key: "owes-2-account", url: "/customers", pre: async (p) => { await firstRow(p); await p.getByRole("tab", { name: "Account", exact: true }).click(); await p.waitForTimeout(900); }, marks: [T("Owes"), T("Credit available")], minH: 480 },

  // ---- 6 Money
  { key: "recon-1-page", url: "/payments/reconciliation", marks: [BX("Upload statement"), BX("Match now"), TAB("Reported by provider"), (p) => p.getByRole("button", { name: "Match", exact: true }).first()] },
  { key: "reports-1-pl", url: "/finance/reports", marks: [TAB("Profit and loss"), LB("From"), BX("Download CSV")], minH: 480 },
  { key: "expense-1-new", url: "/finance/expenses", pre: CL("New expense"), marks: [LB("Description"), LB("Amount"), LB("Paid from"), BX("Save and submit")] },
  { key: "bankrec-1-page", url: "/finance/bank", pre: firstRow, marks: [T("Statement balance"), BX("Load statement"), BX("Mark cleared"), BX("Complete")], minH: 480 },
  { key: "month-1-periods", url: "/finance/setup", marks: [H("Periods and posting rules"), (p) => p.getByRole("button", { name: "Actions" }).first(), BX("Open a period")] },

  // ---- 7 People
  { key: "employee-1-new", url: "/employees", pre: CL("New employee"), marks: [LB("Full name"), LB("Branch"), H("Identity and registrations"), BX("Save")] },
  { key: "attendance-1-page", url: "/attendance", marks: [TAB("Daily records"), LB("From"), (p) => p.getByRole("button", { name: "Record attendance" }).first()] },
  { key: "leave-1-request", url: "/leave", pre: CL("Request leave"), marks: [T("Myself"), LB("Leave type"), LB("First day"), BX("Submit request")] },
  { key: "payroll-1-setup", url: "/payroll-setup", marks: [TAB("Statutory rules"), TAB("Pay components"), BX("New rule")], minH: 420 },
  { key: "payroll-2-run", url: "/payroll", pre: firstRow, marks: [T("Calculated"), T("Employees"), H("Review"), BX("Submit for approval")], minH: 520 },

  // ---- 8 Intelligence
  { key: "checks-1-findings", url: "/intelligence/things", marks: [TAB("Open"), C("main select"), T("Look into it")], minH: 520 },
  { key: "checks-2-settings", url: "/intelligence/watching", marks: [T("Set up again"), T("Look again now"), T("Tell me when the day's cash")], minH: 520 },
  { key: "quick-1-page", url: "/intelligence/setup", marks: [T("1. What matters to you?"), T("Send me a daily summary"), BX("Turn it on")], minH: 520 },
  { key: "brief-1-page", url: "/intelligence/summary", marks: [LB("Send by"), BX("Save"), T("See it first, or send it now")], minH: 520 },
  { key: "finding-1-open", url: "/intelligence/things", pre: async (p) => { await p.getByRole("button", { name: "Look into it" }).or(p.getByRole("link", { name: "Look into it" })).first().click(); await p.waitForTimeout(1500); }, marks: [BX("I'm on it"), T("What we noticed"), T("The facts")], minH: 520 },
  { key: "actions-1-page", url: "/intelligence/suggestions", marks: [TAB("Waiting for you"), TAB("Decided")], minH: 300 },
  { key: "ask-1-ai", url: "/admin/settings", pre: CL("AI assistant"), marks: [T("Explains things in plain words"), T("What it does"), T("What is sent to the AI provider")], minH: 520 },
  { key: "alerts-1-account", url: "/admin/account", marks: [LB("Urgent alerts"), LB("Daily summary"), T("Quiet hours"), BX("Save")], minH: 520 },
  { key: "level-1-page", url: "/intelligence/how-much", marks: [C("label:has(input[type=radio])"), T("(now)"), (p) => p.locator("label:has(input[type=radio])").nth(3)], minH: 520 },
  { key: "connect-1-new", url: "/connect/new", marks: [H("Just drop your file"), H("Your ERP"), H("Statements and exports")], minH: 520 },
  { key: "coverage-1-panel", url: "/intelligence", pre: async (p) => { await p.getByText("What Ziira can check").first().scrollIntoViewIfNeeded(); await p.waitForTimeout(400); }, marks: [T("of Ziira's checks can run"), T("Cash and sales"), T("Connect more to check more")], minH: 420 },

  // ---- 9 Settings
  { key: "addons-1-page", ten: "shop", url: "/addons", marks: [BX("Change edition"), C("input[placeholder='Search add-ons']"), (p) => p.getByRole("button", { name: "Switch off" }).first()], minH: 520 },
  { key: "import-1-kind", ten: "shop", url: "/imports/new", pre: async (p) => { await p.getByText("Products and prices", { exact: true }).click(); await p.waitForTimeout(500); }, marks: [T("What are you importing?"), BX("Download sample file"), BX("Read the file")], minH: 520 },
  { key: "numbers-1-page", url: "/admin/settings", pre: CL("Document numbers"), marks: [(p) => p.getByRole("columnheader", { name: "Document" }), (p) => p.getByRole("columnheader", { name: "Prefix" }), (p) => p.getByRole("columnheader", { name: "Next number" }), (p) => p.getByRole("button", { name: "Edit" }).first()] },
  { key: "security-1-roles", url: "/admin/roles", marks: [BX("New role"), T("Accountant"), (p) => p.getByRole("button", { name: "View" }).first()] },
  { key: "channels-1-page", url: "/messaging/channels", marks: [H("SMS"), H("Email"), H("Latest messages")], minH: 520 },
];
