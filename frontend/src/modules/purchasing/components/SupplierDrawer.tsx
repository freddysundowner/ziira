import { type FormEvent } from "react";

import { api, Button, Drawer, Field, FormGrid, Input, NumberInput, orNull, Select, toast, unwrap, useCompany, useFormState, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { SUPPLIER_STATUSES } from "../lib";
import type { Supplier } from "../types";

/** Create a supplier, or edit one when `supplier` is given. Mount it only while open. */
export function SupplierDrawer({ supplier, onClose, onSaved }: { supplier?: Supplier; onClose: () => void; onSaved?: (s: Supplier) => void }) {
  const { t } = useTranslation("purchasing");
  const qc = useQueryClient();
  const { company, companies } = useCompany();
  const f = useFormState({
    company_id: supplier?.company_id ?? company?.id ?? "", code: supplier?.code ?? "", name: supplier?.name ?? "", tax_id: supplier?.tax_id ?? "",
    phone: supplier?.phone ?? "", email: supplier?.email ?? "", terms: String(supplier?.payment_terms_days ?? 0), status: supplier?.status ?? "active",
  });

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      const common = { name: v.name.trim(), tax_id: orNull(v.tax_id), phone: orNull(v.phone), email: orNull(v.email), payment_terms_days: Number(v.terms) || 0 };
      return supplier
        ? unwrap(api.PATCH("/api/v1/purchasing/suppliers/{supplier_id}", { params: { path: { supplier_id: supplier.id } }, body: { ...common, status: v.status as "active" } }))
        : unwrap(api.POST("/api/v1/purchasing/suppliers", { body: { ...common, company_id: v.company_id, code: v.code.trim() } }));
    },
    onSuccess: (s) => {
      void qc.invalidateQueries({ queryKey: ["purchasing"] });
      toast(t(supplier ? "supplierSaved" : "supplierCreated", { name: s.name }), "ok");
      onSaved?.(s);
      onClose();
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open onClose={onClose} title={t(supplier ? "editSupplier" : "newSupplier")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="supplier-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="supplier-form" onSubmit={submit} className="space-y-4">
        {!supplier && companies.length > 1 && (
          <Field label={t("company")}><Select {...f.bind("company_id")}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
        )}
        <FormGrid>
          {!supplier && <Field label={t("code")} required hint={t("codeHint")} error={f.error("code")}><Input {...f.bind("code")} required maxLength={20} /></Field>}
          <Field label={t("name")} required error={f.error("name")}><Input {...f.bind("name")} required maxLength={200} autoFocus /></Field>
          <Field label={t("phone")} error={f.error("phone")}><Input type="tel" {...f.bind("phone")} maxLength={30} /></Field>
          <Field label={t("email")} error={f.error("email")}><Input type="email" {...f.bind("email")} maxLength={200} /></Field>
          <Field label={t("taxId")} error={f.error("tax_id")}><Input {...f.bind("tax_id")} maxLength={30} /></Field>
          <Field label={t("terms")} hint={t("termsHint")} error={f.error("payment_terms_days")}><NumberInput value={f.values.terms} onChange={(v) => f.set("terms", v.replace(/\./g, ""))} /></Field>
        </FormGrid>
        {supplier && (
          <Field label={t("status")} hint={t("statusHint")} error={f.error("status")}>
            <Select {...f.bind("status")}>{SUPPLIER_STATUSES.map((s) => <option key={s} value={s}>{t(`statuses.${s}`)}</option>)}</Select>
          </Field>
        )}
      </form>
    </Drawer>
  );
}
