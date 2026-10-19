import { type FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api, Alert, Button, Drawer, Field, FormGrid, Input, orNull, Select, Switch, Textarea, toast, today, unwrap, useCan, useCompany, useCurrency, useFormState,
  useMutation, useQueryClient, useTranslation, money,
} from "@/sdk";

import { CustomerPicker, useBranchChoice, useInvoicing, usePlans } from "../hooks";
import { credits } from "../logic";
import { memberPath } from "../public";

const empty = { plan_id: "", start_date: "", end_date: "", notes: "" };

/** Sign a customer up to a plan in a drawer. The first period is invoiced when invoices are on and the plan has a service item. */
export function MemberForm({ open, onClose, customerId }: { open: boolean; onClose: () => void; customerId?: string }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { company } = useCompany();
  const currency = useCurrency(company?.id);
  const f = useFormState({ ...empty, start_date: today() });
  const [customer, setCustomer] = useState(customerId ?? "");
  const [branch, setBranch] = useState("");
  const [invoiceIt, setInvoiceIt] = useState(true);
  const [waiveJoining, setWaiveJoining] = useState(false);
  const canWaive = useCan("memberships.credits");
  const plans = usePlans(company?.id, "active");
  const invoicing = useInvoicing();
  const { branchId, field: branchField } = useBranchChoice(company?.id ?? "", branch, setBranch);
  const plan = plans.data?.find((p) => p.id === f.values.plan_id);
  const canInvoice = invoicing === true && !!plan?.service_product_id && Number(plan.fee) > 0;

  const { reset } = f;
  useEffect(() => { if (open) { reset(); setCustomer(customerId ?? ""); setInvoiceIt(true); setWaiveJoining(false); } }, [open, customerId]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/members", { body: {
      plan_id: f.values.plan_id, customer_id: customer, branch_id: branchId, start_date: f.values.start_date || null,
      end_date: orNull(f.values.end_date), notes: orNull(f.values.notes), auto_invoice: canInvoice ? invoiceIt : false, waive_joining_fee: waiveJoining } })),
    onSuccess: (m) => {
      void qc.invalidateQueries({ queryKey: ["memberships"] });
      toast(t("signedUp", { name: m.customer_name ?? m.number }), "ok");
      onClose();
      navigate(memberPath(m.id));
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={t("signUpTitle")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button type="submit" form="member-form" loading={save.isPending} disabled={!customer || !f.values.plan_id}>{t("signUp")}</Button></>}>
      <form id="member-form" onSubmit={submit} className="space-y-4">
        <CustomerPicker value={customer} onChange={setCustomer} required error={f.error("customer_id")} />
        <Field label={t("plan")} required error={f.error("plan_id")}>
          <Select value={f.values.plan_id} onChange={(e) => f.set("plan_id", e.target.value)} required>
            <option value="">{t("pickPlan")}</option>
            {plans.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </Field>
        {plans.data?.length === 0 && <Alert tone="warn">{t("noPlansYet")}</Alert>}
        {plan && (
          <p className="rounded-md bg-surface-2 p-3 text-sm text-muted">
            {t("planSummary", { fee: money(plan.fee, currency), every: t(`intervals.${plan.billing_interval}`), credits: credits(plan.credits_per_period), discount: plan.discount_percent })}
          </p>
        )}
        {plan && Number(plan.joining_fee) > 0 && (
          <div className="space-y-2">
            <Alert tone="info">{t("joiningFeeNote", { amount: money(plan.joining_fee, currency) })}</Alert>
            {canWaive && <Switch checked={waiveJoining} onChange={setWaiveJoining} label={t("waiveJoiningFee")} />}
          </div>
        )}
        {branchField}
        <FormGrid>
          <Field label={t("startDate")} error={f.error("start_date")}><Input type="date" {...f.bind("start_date")} /></Field>
          <Field label={t("endDate")} hint={t("endDateHint")} error={f.error("end_date")}><Input type="date" {...f.bind("end_date")} /></Field>
        </FormGrid>
        {plan && Number(plan.fee) > 0 && (canInvoice
          ? <Switch checked={invoiceIt} onChange={setInvoiceIt} label={t("invoiceTheFee")} />
          : <Alert tone="info">{invoicing === false ? t("invoicingOff") : t("planNeedsService")}</Alert>)}
        <Field label={t("notes")} error={f.error("notes")}><Textarea rows={2} maxLength={1000} {...f.bind("notes")} /></Field>
      </form>
    </Drawer>
  );
}
