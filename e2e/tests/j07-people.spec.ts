import { code } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, test } from "../lib/test";
import { drawer, lbl } from "../lib/ui";

// J7: an employee, basic pay proposed by one person and approved by another, a payroll rule defined by one and verified
// by another, a payroll run calculated and approved by someone else, and the payslip.
test("J7 people and payroll with separation of duties", async ({ page, second }) => {
  const s = shared();
  const name = `Jane ${code(5)}`;
  const month = new Date();
  const first = new Date(month.getFullYear(), month.getMonth(), 1).toLocaleDateString("en-CA");
  const last = new Date(month.getFullYear(), month.getMonth() + 1, 0).toLocaleDateString("en-CA");

  await signIn(page, s.owner);
  await page.goto("/employees");
  await page.getByRole("button", { name: "New employee" }).first().click();
  await drawer(page).getByLabel(lbl("Full name")).fill(name);
  await drawer(page).getByLabel(lbl("Hire date")).fill("2026-01-01");
  await drawer(page).getByRole("button", { name: "Save", exact: true }).click();
  await page.getByRole("cell", { name }).click();
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await checkAccessibility(page, "employee");

  // --- basic pay: proposed by the owner, who may not approve it
  await page.getByRole("tab", { name: "Pay", exact: true }).click();
  await page.getByRole("button", { name: "Propose basic pay" }).click();
  await drawer(page).getByLabel(/^Basic pay/).fill("1000");
  await drawer(page).getByLabel(lbl("From")).fill(first);
  await drawer(page).getByRole("button", { name: "Propose", exact: true }).click();
  await expect(page.getByText("Proposed. Someone else must approve it before payroll uses it.")).toBeVisible();
  await expect(page.getByText("Another person must decide")).toBeVisible();

  const sam = await second(s.second);
  await sam.goto("/employees");
  await sam.getByRole("cell", { name }).click();
  await sam.getByRole("tab", { name: "Pay", exact: true }).click();
  await sam.getByRole("button", { name: "Approve", exact: true }).click();
  await sam.getByRole("dialog").getByRole("button", { name: "Approve", exact: true }).click();
  await expect(sam.getByText("Approved.")).toBeVisible();

  // --- a pension rule: 5% from the employee; defined by the owner, verified by Sam
  await page.goto("/payroll-setup");
  await page.getByRole("button", { name: "New rule" }).first().click();
  const modal = page.getByRole("dialog");
  await modal.getByLabel(lbl("Code")).fill("PENSION");
  await modal.getByLabel(lbl("Rule name")).fill("Pension");
  await modal.getByLabel(lbl("Source")).fill("Company pension scheme rules, section 4");
  await modal.getByLabel("How it is worked out").first().selectOption("rate");
  await modal.getByLabel(lbl("Rate (%)")).first().fill("5");
  await modal.getByRole("button", { name: "Save rule" }).click();
  await expect(page.getByText(/Rule PENSION saved/)).toBeVisible();

  // the person who defined the rule may not verify it
  await page.getByRole("button", { name: "Actions" }).first().click();
  await expect(page.getByRole("menuitem", { name: "Verify" })).toBeDisabled();
  await page.keyboard.press("Escape");

  await sam.goto("/payroll-setup");
  await sam.getByRole("button", { name: "Actions" }).first().click();
  await sam.getByRole("menuitem", { name: "Verify" }).click();
  await sam.getByRole("dialog").getByRole("button", { name: "Verify" }).click();
  await expect(sam.getByText("Rule verified.")).toBeVisible();

  // --- the run: prepared by the owner, approved by Sam
  await page.goto("/payroll");
  await page.getByRole("button", { name: "New payroll run" }).first().click();
  await drawer(page).getByLabel(lbl("Period starts")).fill(first);
  await drawer(page).getByLabel(lbl("Period ends")).fill(last);
  await drawer(page).getByLabel(lbl("Pay date")).fill(last);
  await drawer(page).getByRole("button", { name: "Create run" }).click();
  await page.waitForURL(/\/payroll\/[0-9a-f-]+$/);
  await page.getByRole("button", { name: "Calculate" }).click();
  await expect(page.getByText("Run calculated.")).toBeVisible();
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByText("Sent for approval.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();       // the preparer may not approve
  const runUrl = page.url();

  await sam.goto(new URL(runUrl).pathname);
  await sam.getByRole("button", { name: "Approve", exact: true }).click();
  await sam.getByRole("dialog").getByRole("button", { name: "Approve", exact: true }).click();
  await expect(sam.getByText("Run approved.")).toBeVisible();

  // --- the payslip: 1000.00 basic less 5% pension = 950.00 net
  await page.reload();
  await page.getByRole("link", { name: new RegExp(name) }).first().click();
  await expect(page.getByText("1,000.00").first()).toBeVisible();
  await expect(page.getByText("50.00").first()).toBeVisible();
  await expect(page.getByText("950.00").first()).toBeVisible();
  await checkAccessibility(page, "payslip");
});
