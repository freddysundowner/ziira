import { type FormEvent, useEffect } from "react";

import { api, Button, CustomFields, Drawer, Field, NumberInput, Select, Textarea, toast, unwrap, useFormState, useMutation, useTranslation } from "@/sdk";

import { useRefresh } from "../hooks";
import { type Client, GROUPINGS } from "../types";

/** How a client is billed: days to pay, how invoice lines are grouped, notes for whoever invoices. */
export function ClientTermsDrawer({ client, companyId, onClose }: { client: Client | null; companyId: string; onClose: () => void }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const f = useFormState({ days: "", group: "", notes: "", markup: "" });
  const { reset, set } = f;
  useEffect(() => {
    if (!client) return;
    reset();
    set("days", client.payment_terms_days === null ? "" : String(client.payment_terms_days));
    set("group", client.invoice_group_by ?? "");
    set("notes", client.billing_notes ?? "");
    set("markup", client.expense_markup_percent ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client?.customer_id]);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PUT("/api/v1/timebilling/clients/{customer_id}", { params: { path: { customer_id: client!.customer_id } }, body: {
      company_id: companyId, payment_terms_days: f.values.days === "" ? null : Number(f.values.days), invoice_group_by: (f.values.group || null) as "project" | null,
      billing_notes: f.values.notes.trim() || null, active: true, expense_markup_percent: f.values.markup === "" ? null : f.values.markup } })),
    onSuccess: () => { void refresh(); toast(t("clients.saved"), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Drawer open={!!client} onClose={onClose} title={t("clients.editTitle", { name: client?.name ?? "" })}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="client-terms" loading={save.isPending}>{t("save")}</Button></>}>
      <form id="client-terms" onSubmit={submit} className="space-y-4">
        <Field label={t("clients.terms")} hint={t("clients.termsHint")} error={f.error("payment_terms_days")}><NumberInput value={f.values.days} onChange={(v) => f.set("days", v.replace(/\./g, ""))} placeholder="30" /></Field>
        <Field label={t("clients.grouping")} hint={t("clients.groupingHint")} error={f.error("invoice_group_by")}>
          <Select {...f.bind("group")}><option value="">{t("clients.businessDefault")}</option>{GROUPINGS.map((g) => <option key={g} value={g}>{t(`grouping.${g}`)}</option>)}</Select>
        </Field>
        <Field label={t("clients.markup")} hint={t("clients.markupHint")} error={f.error("expense_markup_percent")}><NumberInput value={f.values.markup} onChange={(v) => f.set("markup", v)} placeholder="—" /></Field>
        <Field label={t("clients.notes")} hint={t("clients.notesHint")} error={f.error("billing_notes")}><Textarea {...f.bind("notes")} maxLength={2000} /></Field>
      </form>
      {client && <div className="mt-4"><CustomFields entityType="timebilling.client" entityId={client.customer_id} canEdit /></div>}
    </Drawer>
  );
}
