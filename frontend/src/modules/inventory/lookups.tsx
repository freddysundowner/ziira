import { api, Combobox, Field, Select, type Option, unwrap, useCompany, useQuery } from "@/sdk";

import { fetchAll, type StockBalance, type StockProduct } from "./logic";

/** Every stock location the user may see (a short list: stores, warehouses, in-transit). */
export function useLocations() {
  return useQuery({ queryKey: ["inv-locations"], queryFn: () => unwrap(api.GET("/api/v1/inventory/locations")) });
}

/** Reason codes of one category (e.g. "stock_adjustment"). */
export function useReasons(category: string, enabled = true) {
  return useQuery({
    enabled, queryKey: ["reasons", category],
    queryFn: () => unwrap(api.GET("/api/v1/settings/reason-codes", { params: { query: { category } } })),
  });
}

/** All products and all stock balances, for the screens that look across the whole range (low stock). */
export function useRange(enabled = true) {
  const products = useQuery({
    enabled, queryKey: ["inv-range-products"], staleTime: 60_000,
    queryFn: (): Promise<StockProduct[]> => fetchAll((limit, offset) => unwrap(api.GET("/api/v1/products/products", { params: { query: { limit, offset } } }))),
  });
  const balances = useQuery({
    enabled, queryKey: ["inv-range-balances"], staleTime: 60_000,
    queryFn: (): Promise<StockBalance[]> => fetchAll((limit, offset) => unwrap(api.GET("/api/v1/inventory/balances", { params: { query: { limit, offset } } }))),
  });
  return { products, balances };
}

/** A product's name by id (cached with the product page's own query, so a table of movements asks once per product). */
export function ProductName({ id }: { id: string }) {
  const p = useQuery({
    queryKey: ["product", id], staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/products/products/{product_id}", { params: { path: { product_id: id } } })),
  });
  if (!p.data) return <span className="text-muted">{p.error ? id.slice(0, 8) : "…"}</span>;
  return <span><span className="font-medium">{p.data.name}</span> <span className="font-mono text-xs text-muted">{p.data.sku}</span></span>;
}

/** Look a product up on the server as the person types. */
export function searchProducts(text: string): Promise<Option[]> {
  return unwrap(api.GET("/api/v1/products/products", { params: { query: { search: text || undefined, limit: 20 } } }))
    .then((rows) => rows.filter((p) => p.is_active).map((p) => ({ value: p.id, label: p.name, hint: p.sku })));
}

export function ProductPicker({ value, label, onChange, id, clearable, placeholder }: {
  value: string; label?: string; onChange: (id: string, name: string) => void; id?: string; clearable?: boolean; placeholder?: string;
}) {
  return <Combobox id={id} value={value} selectedLabel={label} search={searchProducts} clearable={clearable} placeholder={placeholder}
    onChange={(v, o) => onChange(v, o?.label ?? "")} />;
}

export const locationLabel = (l: { code: string; name: string }) => `${l.code} · ${l.name}`;

/** The company a form works in, with a picker only when the business has several. */
export function useFormCompany(chosen: string) {
  const { company, companies } = useCompany();
  const companyId = chosen || company?.id || "";
  return { companyId, companies, branches: companies.find((c) => c.id === companyId)?.branches ?? [] };
}

export function CompanyField({ label, value, onChange, companies }: {
  label: string; value: string; onChange: (id: string) => void; companies: { id: string; name: string }[];
}) {
  if (companies.length < 2) return null;
  return <Field label={label}><Select value={value} onChange={(e) => onChange(e.target.value)}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>;
}
