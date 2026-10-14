import { useState } from "react";

import {
  api, Alert, Badge, Button, Card, DataTable, Drawer, Field, formatDate, FormGrid, NumberInput, type Schemas, Textarea, toast, unwrap, useCan, useFormState,
  useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { creditTone } from "../logic";
import { Amount } from "./Amount";

/** Credit limit, payment terms and every change made to them. Raising the limit may wait for an approver. */
export function CreditTab({ customer }: { customer: Schemas["CustomerOut"] }) {
  const { t } = useTranslation("crm");
  const qc = useQueryClient();
  const canManage = useCan("customers.manage");
  const [open, setOpen] = useState(false);
  const key = ["customer-credit", customer.id];
  const history = useQuery({ queryKey: key, queryFn: () => unwrap(api.GET("/api/v1/crm/customers/{customer_id}/credit", { params: { path: { customer_id: customer.id } } })) });
  const f = useFormState({ credit_limit: customer.credit_limit, payment_terms_days: String(customer.payment_terms_days), reason: "" });
  const waiting = history.data?.some((v) => v.status === "pending_approval");

  const change = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/crm/customers/{customer_id}/credit", { params: { path: { customer_id: customer.id } }, body: {
      credit_limit: f.values.credit_limit || "0", payment_terms_days: Number(f.values.payment_terms_days) || 0, reason: f.values.reason.trim() } })),
    onSuccess: (v) => {
      void qc.invalidateQueries({ queryKey: key });
      void qc.invalidateQueries({ queryKey: ["customer", customer.id] });
      toast(t(v.status === "active" ? "creditApplied" : "creditWaiting"), v.status === "active" ? "ok" : "info");
      setOpen(false);
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });

  const openForm = () => { f.set("credit_limit", customer.credit_limit); f.set("payment_terms_days", String(customer.payment_terms_days)); f.set("reason", ""); setOpen(true); };

  return (
    <div className="space-y-4">
      <Card title={t("creditNow")} actions={canManage && <Button size="sm" disabled={waiting} onClick={openForm}>{t("changeCredit")}</Button>}>
        <dl className="grid gap-4 sm:grid-cols-2">
          <div><dt className="text-xs font-medium uppercase tracking-wide text-muted">{t("creditLimit")}</dt><dd className="tnum mt-0.5 text-xl font-semibold"><Amount value={customer.credit_limit} companyId={customer.company_id} /></dd></div>
          <div><dt className="text-xs font-medium uppercase tracking-wide text-muted">{t("terms")}</dt><dd className="mt-0.5 text-xl font-semibold">{t("days", { count: customer.payment_terms_days })}</dd></div>
        </dl>
        {waiting && <Alert tone="warn" className="mt-4">{t("creditPending")}</Alert>}
      </Card>
      <Card title={t("creditHistory")} flush>
        <DataTable
          rows={history.data} loading={history.isLoading} error={history.error?.message} onRetry={() => void history.refetch()} rowKey={(v) => v.id}
          empty={{ title: t("noCreditHistory") }}
          columns={[
            { header: t("date"), cell: (v) => formatDate(v.valid_from, true) },
            { header: t("creditLimit"), align: "right", cell: (v) => <Amount value={v.credit_limit} companyId={customer.company_id} /> },
            { header: t("previousLimit"), hideBelow: "md", align: "right", cell: (v) => (v.previous_limit ? <Amount value={v.previous_limit} companyId={customer.company_id} /> : "—") },
            { header: t("terms"), hideBelow: "sm", align: "right", cell: (v) => t("days", { count: v.payment_terms_days }) },
            { header: t("reason"), hideBelow: "lg", cell: (v) => v.reason ?? "—" },
            { header: t("status"), cell: (v) => <Badge tone={creditTone(v.status)}>{t(`creditStatuses.${v.status}`, v.status)}</Badge> },
          ]}
        />
      </Card>
      <Drawer open={open} onClose={() => setOpen(false)} title={t("changeCredit")}
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>{t("cancel")}</Button><Button type="submit" form="credit-form" loading={change.isPending}>{t("submit")}</Button></>}>
        <form id="credit-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); change.mutate(); }}>
          <FormGrid>
            <Field label={t("creditLimit")} required error={f.error("credit_limit")}><NumberInput value={f.values.credit_limit} onChange={(v) => f.set("credit_limit", v)} required /></Field>
            <Field label={t("terms")} hint={t("termsHint")} required error={f.error("payment_terms_days")}>
              <NumberInput value={f.values.payment_terms_days} onChange={(v) => f.set("payment_terms_days", v.split(".")[0] ?? "")} required />
            </Field>
          </FormGrid>
          <Field label={t("reason")} required hint={t("creditReasonHint")} error={f.error("reason")}><Textarea {...f.bind("reason")} required /></Field>
          <Alert>{t("creditApprovalNote")}</Alert>
        </form>
      </Drawer>
    </div>
  );
}
