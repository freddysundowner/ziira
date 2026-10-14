import { useEffect, useState } from "react";

import {
  api, Button, Drawer, Field, FormGrid, Input, orNull, Select, toast, unwrap, useCompany, useFormState, useMutation, useQuery, useQueryClient, useTranslation,
  type Schemas,
} from "@/sdk";

import { usePhoneHint } from "./PhoneHint";

type Lead = Schemas["LeadOut"];

export function useSources(enabled = true) {
  return useQuery({ enabled, queryKey: ["lead-sources"], queryFn: () => unwrap(api.GET("/api/v1/crm/lead-sources")) });
}

function initialOf(lead?: Lead) {
  return { name: lead?.name ?? "", business_name: lead?.business_name ?? "", phone: lead?.phone ?? "", email: lead?.email ?? "", source_id: lead?.source_id ?? "", customer_kind: "business" };
}

/** Create (no `lead`) or edit a lead in a drawer. */
export function LeadForm({ open, onClose, lead }: { open: boolean; onClose: () => void; lead?: Lead }) {
  const { t } = useTranslation("crm");
  const qc = useQueryClient();
  const { company, companies } = useCompany();
  const [companyId, setCompanyId] = useState(lead?.company_id ?? "");
  const f = useFormState(initialOf(lead));
  const sources = useSources(open);
  const effectiveCompany = companyId || company?.id || "";
  const phoneHint = usePhoneHint(effectiveCompany);
  const { reset } = f;
  useEffect(() => { if (open) reset(); }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const v = f.values;
      if (lead) {
        return unwrap(api.PATCH("/api/v1/crm/leads/{lead_id}", { params: { path: { lead_id: lead.id } }, body: {
          name: v.name.trim(), business_name: orNull(v.business_name), phone: orNull(v.phone), email: orNull(v.email), source_id: v.source_id || null } }));
      }
      return unwrap(api.POST("/api/v1/crm/leads", { body: {
        company_id: effectiveCompany, name: v.name.trim(), business_name: orNull(v.business_name), phone: orNull(v.phone), email: orNull(v.email),
        source_id: v.source_id || null, customer_kind: v.customer_kind as "business" } }));
    },
    onSuccess: (l) => { void qc.invalidateQueries({ queryKey: ["leads"] }); toast(t(lead ? "leadUpdated" : "leadCreated", { name: l.name }), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });

  return (
    <Drawer open={open} onClose={onClose} title={lead ? t("editLead") : t("newLead")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="lead-form" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="lead-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <Field label={t("contactPerson")} required error={f.error("name")}><Input {...f.bind("name")} required autoFocus /></Field>
        <Field label={t("businessName")} error={f.error("business_name")}><Input {...f.bind("business_name")} /></Field>
        <FormGrid>
          <Field label={t("phone")} hint={phoneHint} error={f.error("phone")}><Input type="tel" {...f.bind("phone")} /></Field>
          <Field label={t("email")} error={f.error("email")}><Input type="email" {...f.bind("email")} /></Field>
        </FormGrid>
        <Field label={t("source")} hint={sources.data?.length === 0 ? t("noSourcesHint") : undefined} error={f.error("source_id")}>
          <Select {...f.bind("source_id")}><option value="">{t("noSource")}</option>{(sources.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>
        </Field>
        {!lead && (
          <>
            <Field label={t("kind")} error={f.error("customer_kind")}>
              <Select {...f.bind("customer_kind")}>{(["business", "individual"] as const).map((k) => <option key={k} value={k}>{t(`kinds.${k}`)}</option>)}</Select>
            </Field>
            {companies.length > 1 && (
              <Field label={t("company")}>
                <Select value={effectiveCompany} onChange={(e) => setCompanyId(e.target.value)}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select>
              </Field>
            )}
          </>
        )}
      </form>
    </Drawer>
  );
}
