import { Plus, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api, Alert, Button, Checkbox, Drawer, Field, IconButton, Input, NumberInput, Select, Textarea, unwrap, useTranslation } from "@/sdk";

import { useClaimsMutation, useUnit } from "../hooks";
import type { Payer } from "../types";
import { CustomerPicker } from "./pickers";

const KINDS = ["insurer", "scheme", "fleet", "employer", "other"] as const;

interface Form {
  name: string; kind: (typeof KINDS)[number]; customerId: string; newCustomer: boolean; phone: string; email: string;
  rates: { key: string; value: string }[]; discount: string; markup: string; paint: string; limit: string; days: string;
  documents: string; contacts: { name: string; role: string; phone: string; email: string }[]; estimateEmail: string; notes: string; active: boolean;
}

const blank = (): Form => ({
  name: "", kind: "insurer", customerId: "", newCustomer: true, phone: "", email: "", rates: [{ key: "default", value: "" }], discount: "0", markup: "0", paint: "", limit: "", days: "30",
  documents: "", contacts: [], estimateEmail: "", notes: "", active: true,
});

const fromPayer = (p: Payer): Form => ({
  name: p.name, kind: p.kind as Form["kind"], customerId: p.customer_id ?? "", newCustomer: false, phone: "", email: "",
  rates: Object.entries(p.labour_rates).map(([key, value]) => ({ key, value: String(value) })), discount: String(Number(p.parts_discount_pct)), markup: String(Number(p.parts_markup_pct)),
  paint: p.paint_rate ?? "", limit: p.approval_limit ?? "", days: String(p.payment_days), documents: p.required_documents.join("\n"),
  contacts: p.contacts.map((c) => ({ name: String(c.name ?? ""), role: String(c.role ?? ""), phone: String(c.phone ?? ""), email: String(c.email ?? "") })),
  estimateEmail: p.estimate_email ?? "", notes: p.notes ?? "", active: p.is_active,
});

/** Set up a payer: who they are, which customer account they are invoiced on, and their terms (rates, parts rules, limit, days, documents, contacts). */
export function PayerDrawer({ open, payer, companyId, onClose }: { open: boolean; payer: Payer | null; companyId: string; onClose: () => void }) {
  const { t } = useTranslation("claims");
  const crm = useUnit("crm");
  const [f, setF] = useState<Form>(blank());
  const [tried, setTried] = useState(false);
  useEffect(() => { if (open) { setF(payer ? fromPayer(payer) : blank()); setTried(false); } }, [open, payer]);
  const set = (patch: Partial<Form>) => setF((x) => ({ ...x, ...patch }));
  const rates = Object.fromEntries(f.rates.filter((r) => r.key.trim() && r.value.trim()).map((r) => [r.key.trim().toLowerCase(), r.value.trim()]));
  const contacts = f.contacts.filter((c) => c.name.trim());
  const documents = f.documents.split("\n").map((d) => d.trim()).filter(Boolean);
  const save = useClaimsMutation(() => payer
    ? unwrap(api.PATCH("/api/v1/claims/payers/{payer_id}", { params: { path: { payer_id: payer.id } }, body: {
      name: f.name.trim(), kind: f.kind, customer_id: f.customerId || null, labour_rates: rates, parts_discount_pct: f.discount || "0", parts_markup_pct: f.markup || "0",
      paint_rate: f.paint.trim() || null, approval_limit: f.limit.trim() || null, payment_days: Number(f.days) || 0, required_documents: documents, contacts,
      estimate_email: f.estimateEmail.trim() || null, notes: f.notes.trim() || null, is_active: f.active } }))
    : unwrap(api.POST("/api/v1/claims/payers", { body: {
      company_id: companyId, name: f.name.trim(), kind: f.kind, customer_id: f.customerId || null,
      new_customer: crm && !f.customerId && f.newCustomer ? { name: f.name.trim(), phone: f.phone.trim() || null, email: f.email.trim() || null } : null,
      labour_rates: rates, parts_discount_pct: f.discount || "0", parts_markup_pct: f.markup || "0", paint_rate: f.paint.trim() || null,
      approval_limit: f.limit.trim() || null, payment_days: Number(f.days) || 0, required_documents: documents, contacts,
      estimate_email: f.estimateEmail.trim() || null, notes: f.notes.trim() || null } })),
  { silent: true, done: t("payers.saved"), onDone: onClose });
  const nameBad = !f.name.trim();
  return (
    <Drawer open={open} onClose={onClose} title={payer ? t("payers.editTitle", { name: payer.name }) : t("payers.newTitle")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => { setTried(true); if (!nameBad) save.mutate(undefined); }}>{t("common.save")}</Button></>}>
      <div className="space-y-5">
        {save.error && <Alert tone="bad">{save.error.message}</Alert>}
        <Field label={t("payers.name")} required error={tried && nameBad ? t("payers.nameNeeded") : null}><Input value={f.name} maxLength={160} onChange={(e) => set({ name: e.target.value })} /></Field>
        <Field label={t("payers.kind")}><Select value={f.kind} onChange={(e) => set({ kind: e.target.value as Form["kind"] })}>{KINDS.map((k) => <option key={k} value={k}>{t(`payers.kinds.${k}`)}</option>)}</Select></Field>
        {crm && (
          <fieldset className="space-y-3 rounded-xl border border-line p-3">
            <legend className="px-1 text-sm font-semibold">{t("payers.account")}</legend>
            <p className="text-xs text-muted">{t("payers.accountHint")}</p>
            <Field label={t("payers.customer")}><CustomerPicker value={f.customerId} onChange={(v) => set({ customerId: v })} /></Field>
            {!payer && !f.customerId && (
              <>
                <Checkbox label={t("payers.makeAccount")} checked={f.newCustomer} onChange={(e) => set({ newCustomer: e.target.checked })} />
                {f.newCustomer && (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label={t("payers.phone")}><Input type="tel" value={f.phone} maxLength={40} onChange={(e) => set({ phone: e.target.value })} /></Field>
                    <Field label={t("payers.email")}><Input type="email" value={f.email} maxLength={200} onChange={(e) => set({ email: e.target.value })} /></Field>
                  </div>
                )}
              </>
            )}
          </fieldset>
        )}
        <fieldset className="space-y-3 rounded-xl border border-line p-3">
          <legend className="px-1 text-sm font-semibold">{t("payers.terms")}</legend>
          <div>
            <p className="mb-1 text-sm font-medium">{t("payers.labourRates")}</p>
            <p className="mb-2 text-xs text-muted">{t("payers.labourRatesHint")}</p>
            {f.rates.map((r, i) => (
              <div key={i} className="mb-2 flex items-center gap-2">
                <Input aria-label={t("payers.workType")} placeholder={t("payers.workType")} value={r.key} maxLength={40} onChange={(e) => set({ rates: f.rates.map((x, at) => (at === i ? { ...x, key: e.target.value } : x)) })} />
                <NumberInput aria-label={t("payers.rate")} placeholder={t("payers.rate")} value={r.value} inputMode="decimal" onChange={(v) => set({ rates: f.rates.map((x, at) => (at === i ? { ...x, value: v } : x)) })} />
                <IconButton label={t("common.remove")} onClick={() => set({ rates: f.rates.filter((_, at) => at !== i) })}><X className="h-4 w-4" /></IconButton>
              </div>
            ))}
            <Button size="sm" variant="ghost" onClick={() => set({ rates: [...f.rates, { key: "", value: "" }] })}><Plus className="h-4 w-4" />{t("payers.addRate")}</Button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("payers.paintRate")}><NumberInput value={f.paint} inputMode="decimal" onChange={(v) => set({ paint: v })} /></Field>
            <Field label={t("payers.limit")} hint={t("payers.limitHint")}><NumberInput value={f.limit} inputMode="decimal" onChange={(v) => set({ limit: v })} /></Field>
            <Field label={t("payers.discount")} hint={t("payers.discountHint")}><NumberInput value={f.discount} inputMode="decimal" onChange={(v) => set({ discount: v })} /></Field>
            <Field label={t("payers.markup")}><NumberInput value={f.markup} inputMode="decimal" onChange={(v) => set({ markup: v })} /></Field>
            <Field label={t("payers.days")} hint={t("payers.daysHint")}><NumberInput value={f.days} inputMode="numeric" onChange={(v) => set({ days: v })} /></Field>
            <Field label={t("payers.estimateEmail")} hint={t("payers.estimateEmailHint")}><Input type="email" value={f.estimateEmail} maxLength={200} onChange={(e) => set({ estimateEmail: e.target.value })} /></Field>
          </div>
          <Field label={t("payers.documents")} hint={t("payers.documentsHint")}><Textarea value={f.documents} rows={3} onChange={(e) => set({ documents: e.target.value })} /></Field>
        </fieldset>
        <fieldset className="space-y-3 rounded-xl border border-line p-3">
          <legend className="px-1 text-sm font-semibold">{t("payers.contacts")}</legend>
          {f.contacts.map((c, i) => (
            <div key={i} className="grid gap-2 rounded-lg bg-sunken/50 p-2 sm:grid-cols-2">
              <Input aria-label={t("payers.contactName")} placeholder={t("payers.contactName")} value={c.name} maxLength={160} onChange={(e) => set({ contacts: f.contacts.map((x, at) => (at === i ? { ...x, name: e.target.value } : x)) })} />
              <Input aria-label={t("payers.contactRole")} placeholder={t("payers.contactRole")} value={c.role} maxLength={160} onChange={(e) => set({ contacts: f.contacts.map((x, at) => (at === i ? { ...x, role: e.target.value } : x)) })} />
              <Input aria-label={t("payers.phone")} placeholder={t("payers.phone")} type="tel" value={c.phone} maxLength={40} onChange={(e) => set({ contacts: f.contacts.map((x, at) => (at === i ? { ...x, phone: e.target.value } : x)) })} />
              <div className="flex gap-2"><Input aria-label={t("payers.email")} placeholder={t("payers.email")} type="email" value={c.email} maxLength={200} onChange={(e) => set({ contacts: f.contacts.map((x, at) => (at === i ? { ...x, email: e.target.value } : x)) })} /><IconButton label={t("common.remove")} onClick={() => set({ contacts: f.contacts.filter((_, at) => at !== i) })}><X className="h-4 w-4" /></IconButton></div>
            </div>
          ))}
          <Button size="sm" variant="ghost" onClick={() => set({ contacts: [...f.contacts, { name: "", role: "", phone: "", email: "" }] })}><Plus className="h-4 w-4" />{t("payers.addContact")}</Button>
        </fieldset>
        <Field label={t("payers.notes")}><Textarea maxLength={2000} value={f.notes} onChange={(e) => set({ notes: e.target.value })} /></Field>
        {payer && <Checkbox label={t("payers.active")} checked={f.active} onChange={(e) => set({ active: e.target.checked })} />}
      </div>
    </Drawer>
  );
}
