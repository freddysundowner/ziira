import { type FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api, Button, Drawer, Field, FormGrid, Input, NumberInput, orNull, Select, toast, unwrap, useCompany, useFormState, useMutation, useQuery,
  useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import { customerPath } from "../public";
import { usePhoneHint } from "./PhoneHint";

type Customer = Schemas["CustomerOut"];

const empty = { name: "", code: "", kind: "business", phone: "", email: "", tax_id: "", customer_group: "", payment_terms_days: "0", status: "active" };

function initialOf(customer?: Customer) {
  return customer
    ? { ...empty, name: customer.name, kind: customer.kind, phone: customer.phone ?? "", email: customer.email ?? "", tax_id: customer.tax_id ?? "",
        customer_group: customer.customer_group ?? "", status: customer.status }
    : empty;
}

/** Existing group names, offered as suggestions while typing (groups are free text used by price lists). */
function useGroupNames(enabled: boolean): string[] {
  const q = useQuery({
    enabled, queryKey: ["customer-groups"], staleTime: 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/crm/customers", { params: { query: { limit: 200 } } })),
  });
  return [...new Set((q.data ?? []).map((c) => c.customer_group).filter((g): g is string => !!g))].sort();
}

/** Create (no `customer`) or edit a customer in a drawer. */
export function CustomerForm({ open, onClose, customer }: { open: boolean; onClose: () => void; customer?: Customer }) {
  const { t } = useTranslation("crm");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { company, companies } = useCompany();
  const f = useFormState(initialOf(customer));
  const [companyId, setCompanyId] = useState(customer?.company_id ?? "");
  const effectiveCompany = companyId || company?.id || "";
  const groups = useGroupNames(open);
  const phoneHint = usePhoneHint(effectiveCompany);
  const editing = !!customer;

  const { reset } = f;
  useEffect(() => { if (open) reset(); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    meta: { silent: true },
    mutationFn: async () => {
      const v = f.values;
      if (customer) {
        return unwrap(api.PATCH("/api/v1/crm/customers/{customer_id}", { params: { path: { customer_id: customer.id } }, body: {
          name: v.name.trim(), kind: v.kind as "business", phone: orNull(v.phone), email: orNull(v.email), tax_id: orNull(v.tax_id),
          customer_group: orNull(v.customer_group), status: v.status as "active" } }));
      }
      return unwrap(api.POST("/api/v1/crm/customers", { body: {
        company_id: effectiveCompany, name: v.name.trim(), code: orNull(v.code), kind: v.kind as "business", phone: orNull(v.phone), email: orNull(v.email),
        tax_id: orNull(v.tax_id), customer_group: orNull(v.customer_group), payment_terms_days: Number(v.payment_terms_days) || 0 } }));
    },
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ["customers"] });
      void qc.invalidateQueries({ queryKey: ["customer", c.id] });
      toast(t(editing ? "updated" : "created", { name: c.name }), "ok");
      onClose();
      if (!editing) navigate(customerPath(c.id));
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={editing ? t("editCustomer") : t("newCustomer")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="customer-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="customer-form" onSubmit={submit} className="space-y-4">
        <Field label={t("name")} required error={f.error("name")}><Input {...f.bind("name")} required autoFocus /></Field>
        <FormGrid>
          <Field label={t("kind")}>
            <Select {...f.bind("kind")}>{(["business", "individual"] as const).map((k) => <option key={k} value={k}>{t(`kinds.${k}`)}</option>)}</Select>
          </Field>
          {!editing && <Field label={t("code")} hint={t("codeHint")} error={f.error("code")}><Input {...f.bind("code")} maxLength={20} /></Field>}
          {editing && (
            <Field label={t("status")}>
              <Select {...f.bind("status")}>{(["active", "on_hold", "inactive"] as const).map((s) => <option key={s} value={s}>{t(`statuses.${s}`)}</option>)}</Select>
            </Field>
          )}
        </FormGrid>
        <FormGrid>
          <Field label={t("phone")} hint={phoneHint} error={f.error("phone")}><Input type="tel" {...f.bind("phone")} /></Field>
          <Field label={t("email")} error={f.error("email")}><Input type="email" {...f.bind("email")} /></Field>
        </FormGrid>
        <Field label={t("taxId")} hint={t("taxIdHint")} error={f.error("tax_id")}><Input {...f.bind("tax_id")} maxLength={30} /></Field>
        <Field label={t("group")} hint={t("groupHint")} error={f.error("customer_group")}>
          <Input {...f.bind("customer_group")} list="customer-groups" maxLength={60} />
        </Field>
        <datalist id="customer-groups">{groups.map((g) => <option key={g} value={g} />)}</datalist>
        {!editing && (
          <>
            {companies.length > 1 && (
              <Field label={t("company")}>
                <Select value={effectiveCompany} onChange={(e) => setCompanyId(e.target.value)}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
              </Field>
            )}
            <Field label={t("terms")} hint={t("termsHint")} error={f.error("payment_terms_days")}>
              <NumberInput value={f.values.payment_terms_days} onChange={(v) => f.set("payment_terms_days", v.split(".")[0] ?? "")} />
            </Field>
            <p className="text-xs text-muted">{t("creditLater")}</p>
          </>
        )}
      </form>
    </Drawer>
  );
}
