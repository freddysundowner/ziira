import { Plus, Trash2 } from "lucide-react";
import { useCallback, useRef } from "react";

import { api, Combobox, Field, IconButton, money, NumberInput, Select, Switch, unwrap, useTranslation } from "@/sdk";

import type { CheckoutLine, Offer, Resource } from "../types";
import { type LineDraft, productLine, serviceLine } from "./logic";

/** The lines of an open bill: price, discount, who did it, credit; plus adding a product or a service. */
export function LinesEditor({ lines, onChange, served, hasClient, staff, offers, companyId, branchId, currency }: {
  lines: LineDraft[]; onChange: (lines: LineDraft[]) => void; served: readonly CheckoutLine[]; hasClient: boolean; staff: readonly Resource[]; offers: readonly Offer[];
  companyId: string; branchId: string; currency?: string;
}) {
  const { t } = useTranslation("bookings");
  const patch = (key: string, change: Partial<LineDraft>) => onChange(lines.map((l) => (l.key === key ? { ...l, ...change } : l)));
  const found = useRef(new Map<string, { id: string; name: string; price?: string | number | null }>());
  const searchProducts = useCallback(async (text: string) => {
    const rows = await unwrap(api.GET("/api/v1/bookings/retail-items", { params: { query: { company_id: companyId, branch_id: branchId || undefined, search: text.trim() || undefined } } }));
    for (const p of rows) found.current.set(p.id, p);
    return rows.map((p) => ({ value: p.id, label: p.name, hint: p.price != null ? money(p.price, currency) : p.sku }));
  }, [companyId, branchId, currency]);
  const lastStaff = [...lines].reverse().find((l) => l.resource_id)?.resource_id ?? "";

  return (
    <div className="space-y-3">
      {lines.length === 0 && <p className="rounded-xl border border-dashed border-line p-4 text-sm text-muted">{t("checkout.noLines")}</p>}
      <ul className="space-y-3">
        {lines.map((l, i) => {
          const net = served[i]?.net;
          return (
            <li key={l.key} className="rounded-xl border border-line bg-surface p-3 sm:p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate font-semibold">{l.description || "—"}</p>
                  <p className="text-xs text-muted">{t(`checkout.kind.${l.kind}`)}{l.variant && ` · ${l.variant}`}</p>
                </div>
                <div className="flex items-center gap-1">
                  {net != null && <span className="tnum text-sm font-bold">{money(net, currency)}</span>}
                  <IconButton label={t("checkout.removeLine")} onClick={() => onChange(lines.filter((x) => x.key !== l.key))}><Trash2 className="h-4 w-4" /></IconButton>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Field label={t("checkout.price")}><NumberInput value={l.unit_price} onChange={(v) => patch(l.key, { unit_price: v })} /></Field>
                {l.kind === "product" && <Field label={t("checkout.quantity")}><NumberInput value={l.quantity} onChange={(v) => patch(l.key, { quantity: v })} /></Field>}
                <Field label={t("checkout.lineDiscount")}><NumberInput value={l.discount} onChange={(v) => patch(l.key, { discount: v })} /></Field>
                {l.kind !== "fee" && (
                  <Field label={t("checkout.staff")} className={l.kind === "product" ? "" : "col-span-2 sm:col-span-1"}>
                    <Select value={l.resource_id} onChange={(e) => patch(l.key, { resource_id: e.target.value })}>
                      <option value="">{t("checkout.nobody")}</option>
                      {staff.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
                    </Select>
                  </Field>
                )}
              </div>
              {l.kind === "service" && (hasClient || l.use_credit) && (
                <label className="mt-3 flex items-center gap-3 text-sm">
                  <Switch checked={l.use_credit} onChange={(v) => patch(l.key, { use_credit: v })} label={t("checkout.useCredit")} />
                  <span>{t("checkout.useCredit")}</span>
                  {served[i] && Number(served[i].credit_quantity) > 0 && <span className="text-xs text-ok">{t("checkout.creditApplied", { count: Number(served[i].credit_quantity) })}</span>}
                </label>
              )}
            </li>
          );
        })}
      </ul>
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <p className="mb-1 flex items-center gap-1 text-[13px] font-semibold"><Plus className="h-3.5 w-3.5" />{t("checkout.addService")}</p>
          <Combobox value="" placeholder={t("checkout.pickService")}
            options={offers.filter((o) => o.is_active && o.kind !== "class").map((o) => ({ value: o.id, label: o.name, hint: money(o.price, currency) }))}
            onChange={(id) => { const o = offers.find((x) => x.id === id); if (o) onChange([...lines, serviceLine(o, lastStaff)]); }} />
        </div>
        <div>
          <p className="mb-1 flex items-center gap-1 text-[13px] font-semibold"><Plus className="h-3.5 w-3.5" />{t("checkout.addProduct")}</p>
          <Combobox value="" placeholder={t("checkout.searchProduct")} search={searchProducts}
            onChange={(id) => { const item = found.current.get(id); if (item) onChange([...lines, productLine(item)]); }} />
        </div>
      </div>
    </div>
  );
}
