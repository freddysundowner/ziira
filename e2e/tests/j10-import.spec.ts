import { code, company } from "../lib/seed";
import { checkAccessibility, expect, shared, signIn, signedInApi, test } from "../lib/test";

// J10: import products from a CSV: upload, match columns, check (one bad row is flagged), import, and see the reconciliation.
test("J10 import products from a CSV", async ({ page }) => {
  const s = shared();
  const api = await signedInApi(s.owner);
  const { companyId } = await company(api);
  const unit = `UN${code(4)}`.replace(/[^A-Z]/g, "X");
  const taxCode = `TX${code(4)}`.replace(/[^A-Z]/g, "X");
  await api.post("/products/uoms", { code: unit, name: "Import unit" });
  await api.post("/products/tax-codes", { code: taxCode, name: "Import tax", vat_rate: "0" });
  const tag = code(4);
  const csv = [
    "sku,name,unit,tax_code,price",
    `IMP1${tag},Bolt ${tag},${unit},${taxCode},12.50`,
    `IMP2${tag},Nut ${tag},${unit},${taxCode},3.25`,
    `IMP3${tag},Washer ${tag},${unit},${taxCode},1.00`,
    `IMP4${tag},Broken ${tag},NOSUCHUNIT,${taxCode},9.99`,
  ].join("\n");

  await signIn(page, s.owner);
  await page.goto("/imports/new");
  await page.getByText("Products and prices", { exact: true }).click();
  await page.locator('input[type="file"]').setInputFiles({ name: "products.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await checkAccessibility(page, "import: file");
  await page.getByRole("button", { name: "Read the file" }).click();

  // the columns are guessed from the header row
  await expect(page.getByText("Match your columns")).toBeVisible();
  await expect(page.getByText("products.csv has 4 rows.")).toBeVisible();
  await checkAccessibility(page, "import: columns");
  await page.getByRole("button", { name: "Check the file" }).click();

  // the check: 3 ready, 1 with a problem
  await expect(page.getByText("Ready to import", { exact: true })).toBeVisible();
  await expect(page.getByText(/NOSUCHUNIT/).first()).toBeVisible();
  await page.getByRole("button", { name: "Import 3 rows" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Import 3 rows" }).click();

  // the reconciliation
  await expect(page.getByText("Does it add up?")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Imported", { exact: true }).first()).toBeVisible();
  await checkAccessibility(page, "import: report");

  const products = await api.get<any[]>("/products/products?limit=500");
  expect(products.filter((p) => p.sku.startsWith("IMP") && p.sku.endsWith(tag)).map((p) => p.sku).sort()).toEqual([`IMP1${tag}`, `IMP2${tag}`, `IMP3${tag}`]);
  void companyId;
});
