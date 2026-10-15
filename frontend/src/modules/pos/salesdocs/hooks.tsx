import { Link } from "react-router-dom";

import { api, Combobox, type Option, type Schemas, unwrap, useAccess, useQuery, useTranslation } from "@/sdk";

import { customerPath } from "@/modules/crm/public";
import { shortId } from "../lib";

/** Customers found as the person types (only active ones can be sold to). */
export async function searchCustomers(text: string): Promise<Option[]> {
  const rows = await unwrap(api.GET("/api/v1/crm/customers", { params: { query: { search: text || undefined, status: "active", limit: 20 } } }));
  return rows.map((c) => ({ value: c.id, label: c.name, hint: [c.code, c.phone].filter(Boolean).join(" · ") }));
}

export async function searchProducts(text: string): Promise<Option[]> {
  const rows = await unwrap(api.GET("/api/v1/products/products", { params: { query: { search: text || undefined, limit: 20 } } }));
  return rows.map((p) => ({ value: p.id, label: p.name, hint: p.sku }));
}

/** One customer, cached. Quiet when the user may not read customers (names then show as short ids). */
export function useCustomer(id: string | null | undefined) {
  return useQuery({
    enabled: !!id, retry: false, staleTime: 5 * 60_000, queryKey: ["pos-docs-customer", id],
    queryFn: () => unwrap(api.GET("/api/v1/crm/customers/{customer_id}", { params: { path: { customer_id: id ?? "" } } })),
  });
}

export type Customer = Schemas["CustomerOut"];

/** A customer's name from its id (a short id when it cannot be read). */
export function CustomerName({ id, link }: { id: string | null | undefined; link?: boolean }) {
  const customer = useCustomer(id);
  if (!id) return <>—</>;
  const name = customer.data?.name ?? shortId(id);
  return link ? <Link className="text-brand-strong hover:underline" to={customerPath(id)}>{name}</Link> : <>{name}</>;
}

/** A product's name from its id; a short id when the user may not read products. */
export function ProductName({ id }: { id: string }) {
  const product = useQuery({
    retry: false, staleTime: 5 * 60_000, queryKey: ["product-name", id],
    queryFn: () => unwrap(api.GET("/api/v1/products/products/{product_id}", { params: { path: { product_id: id } } })),
  });
  return <span className="font-medium">{product.data?.name ?? shortId(id)}</span>;
}

export function CustomerPicker({ value, onChange, disabled, invalid, clearable, placeholder, id }: {
  id?: string; value: string; onChange: (id: string) => void; disabled?: boolean; invalid?: boolean; clearable?: boolean; placeholder?: string;
}) {
  const { t } = useTranslation("pos");
  const current = useCustomer(value || null);
  return <Combobox id={id} value={value} onChange={(v) => onChange(v)} search={searchCustomers} selectedLabel={current.data?.name} clearable={clearable}
    placeholder={placeholder ?? t("docs.pickCustomer")} disabled={disabled} invalid={invalid} />;
}

export function ProductPicker({ value, onChange, id }: { value: string; onChange: (id: string) => void; id?: string }) {
  const { t } = useTranslation("pos");
  const current = useQuery({
    enabled: !!value, retry: false, staleTime: 5 * 60_000, queryKey: ["product-name", value],
    queryFn: () => unwrap(api.GET("/api/v1/products/products/{product_id}", { params: { path: { product_id: value } } })),
  });
  return <Combobox id={id} value={value} onChange={(v) => onChange(v)} search={searchProducts}
    selectedLabel={current.data ? `${current.data.name} (${current.data.sku})` : undefined} placeholder={t("docs.pickProduct")} />;
}

/** Whether Customers (which the documents are made for) is on for this business. */
export function useHasCustomers(): boolean {
  return useAccess().enabledUnits.has("crm");
}
