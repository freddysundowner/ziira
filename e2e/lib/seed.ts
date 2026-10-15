/** Set-up helpers that use the API (fast) so a journey can start from a realistic business and test its own subject in the browser. */
import type { Api } from "./api";

export interface Company {
  id: string;
  name: string;
  branches: { id: string; name: string; code: string }[];
}

export async function company(api: Api): Promise<{ companyId: string; branchId: string }> {
  const list = await api.get<any[]>("/companies");
  const c = list[0];
  const branches = c.branches ?? (await api.get<any>(`/companies/${c.id}`)).branches;
  return { companyId: c.id, branchId: branches[0].id };
}

export interface Catalogue {
  companyId: string;
  branchId: string;
  uomId: string;
  taxId: string;
  priceListId: string;
  locationId: string;
  deviceId: string;
  products: { id: string; sku: string; name: string; price: number; cost: number }[];
}

let letters = 0;
export const code = (n = 4) => {
  letters++;
  let out = "";
  let x = Date.now() + letters * 7919;
  for (let i = 0; i < n; i++) { out += String.fromCharCode(65 + (x % 26)); x = Math.floor(x / 26) + 13 * (i + 1); }
  return out;
};

/** Unit, 0% tax code (so expected totals are easy to hand-check), default price list, a store, a till device, products with prices and opening stock. */
export async function seedCatalogue(api: Api, products: { name: string; price: number; cost: number; qty: number }[], opts: { taxRate?: number } = {}): Promise<Catalogue> {
  const { companyId, branchId } = await company(api);
  const tag = code(5);
  const uom = await api.post("/products/uoms", { code: `U${tag}`, name: `Unit ${tag}` });
  const tax = await api.post("/products/tax-codes", { code: `T${tag}`, name: `Tax ${tag}`, vat_rate: String(opts.taxRate ?? 0) });
  const lists = await api.get<any[]>("/products/price-lists");
  const list = lists.find((l) => l.is_default) ?? (await api.post("/products/price-lists", { company_id: companyId, name: `List ${tag}`, is_default: true }));
  const loc = await api.post("/inventory/locations", { company_id: companyId, branch_id: branchId, kind: "store", code: `S${tag}`.slice(0, 10), name: `Store ${tag}` });
  const device = await api.post("/pos/devices", { branch_id: branchId, code: `D${tag}`, name: `Till ${tag}`, location_id: loc.id });
  const made: Catalogue["products"] = [];
  for (const p of products) {
    const row = await api.post("/products/products", { company_id: companyId, sku: `${p.name.slice(0, 3).toUpperCase()}${tag}`, name: `${p.name} ${tag}`, base_uom_id: uom.id, tax_code_id: tax.id, product_type: "stock" });
    await api.put(`/products/price-lists/${list.id}/prices`, { product_id: row.id, price: String(p.price) });
    made.push({ id: row.id, sku: row.sku, name: `${p.name} ${tag}`, price: p.price, cost: p.cost });
  }
  const lines = products.map((p, i) => ({ product_id: made[i].id, quantity: String(p.qty), unit_cost: String(p.cost) })).filter((_, i) => products[i].qty > 0);
  if (lines.length) await api.post("/inventory/opening-stock", { company_id: companyId, location_id: loc.id, lines });
  return { companyId, branchId, uomId: uom.id, taxId: tax.id, priceListId: list.id, locationId: loc.id, deviceId: device.id, products: made };
}

/** One person can have one open till: close any the previous journey left open (counted cash = what the till expects). */
export async function closeOpenTills(api: Api): Promise<void> {
  const open = await api.get<any[]>("/pos/tills?status=open");
  for (const t of open) {
    const report = await api.get<any>(`/pos/tills/${t.id}/report`);
    await api.post(`/pos/tills/${t.id}/close`, { counted_cash: String(report.expected_cash) });
  }
}

/** A user (created through the API) holding a built-in role over one branch only (or the whole company when `branchId` is left out). */
export async function scopedUser(api: Api, who: { name: string; email: string; password: string; role: string; companyId: string; branchId?: string }): Promise<void> {
  const roles = await api.get<{ id: string; name: string }[]>("/roles");
  const role = roles.find((r) => r.name === who.role);
  if (!role) throw new Error(`no role ${who.role}`);
  const user = await api.post("/users", { full_name: who.name, email: who.email, password: who.password });
  await api.post(`/users/${user.id}/roles`, { role_id: role.id, scope: who.branchId ? "branch" : "company", company_id: who.companyId, branch_id: who.branchId ?? null });
}

/** An employee with approved pay and an approved payroll run for last month, so a payslip exists. `second` approves what the owner prepares. */
export async function seedPayslip(owner: Api, second: Api, companyId: string): Promise<{ payslipId: string; name: string }> {
  const name = `Pat ${code(5)}`;
  const employee = await owner.post("/people/employees", { company_id: companyId, full_name: name, hire_date: "2024-01-01" });
  const terms = await owner.post(`/people/employees/${employee.id}/terms`, { basic_pay: "1500", valid_from: "2024-01-01" });
  await second.post(`/people/terms/${terms.id}/approve`);
  const now = new Date();
  const iso = (d: Date) => d.toLocaleDateString("en-CA");
  const start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const end = new Date(now.getFullYear(), now.getMonth(), 0);
  const run = await owner.post("/people/payroll-runs", { company_id: companyId, period_start: iso(start), period_end: iso(end), pay_date: iso(end) });
  await owner.post(`/people/payroll-runs/${run.id}/calculate`);
  await owner.post(`/people/payroll-runs/${run.id}/submit`);
  await second.post(`/people/payroll-runs/${run.id}/approve`);
  const slips = await owner.get<{ id: string; full_name: string }[]>(`/people/payroll-runs/${run.id}/payslips`);
  const slip = slips.find((s) => s.full_name === name);
  if (!slip) throw new Error("no payslip for the new employee");
  return { payslipId: slip.id, name };
}

/** A business customer with a credit limit and payment terms (the credit check applies to invoices), made through the API. */
export async function customerWithCredit(api: Api, companyId: string, name: string, limit = 5000, termsDays = 30): Promise<{ id: string; name: string }> {
  const customer = await api.post("/crm/customers", { company_id: companyId, name, payment_terms_days: termsDays });
  await api.post(`/crm/customers/${customer.id}/credit`, { credit_limit: String(limit), payment_terms_days: termsDays, reason: "Test customer" });
  return { id: customer.id, name };
}
