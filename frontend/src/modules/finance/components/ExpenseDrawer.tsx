import { useNavigate } from "react-router-dom";

import {
  api, Button, Combobox, Drawer, Field, FormGrid, Input, NumberInput, orNull, Select, today, toast, unwrap, useFormState, useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import { accountOptions, useAccounts } from "../api";
import type { Scope } from "../scope";

const PAID_FROM = ["cash", "bank", "mobile_money", "card", "other"] as const;
type PaidFrom = (typeof PAID_FROM)[number];

/** Capture an expense. "Save and submit" posts it (or sends it to an approver); "Save draft" keeps it to finish later. */
export function ExpenseDrawer({ open, onClose, scope }: { open: boolean; onClose: () => void; scope: Scope }) {
  if (!open) return null;
  return <ExpenseForm onClose={onClose} scope={scope} />;
}

function ExpenseForm({ onClose, scope }: { onClose: () => void; scope: Scope }) {
  const { t } = useTranslation("finance");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const accounts = useAccounts(scope.companyId);
  const f = useFormState({
    expense_date: today(), description: "", account_id: "", amount: "", tax_amount: "", paid_from: "cash", payee: "", receipt_ref: "",
    branch_id: scope.branchId || (scope.branches.length === 1 ? scope.branches[0].id : ""),
  });

  const save = useMutation({
    meta: { silent: true },
    mutationFn: async (submit: boolean) => {
      const created = await unwrap(api.POST("/api/v1/finance/expenses", { body: {
        company_id: scope.companyId, branch_id: f.values.branch_id || null, expense_date: f.values.expense_date, description: f.values.description.trim(),
        account_id: f.values.account_id, amount: f.values.amount, tax_amount: f.values.tax_amount || "0", paid_from: f.values.paid_from as PaidFrom,
        payee: orNull(f.values.payee), receipt_ref: orNull(f.values.receipt_ref) } }));
      if (!submit) return created;
      try {
        return await unwrap(api.POST("/api/v1/finance/expenses/{expense_id}/submit", { params: { path: { expense_id: created.id } } }));
      } catch (e) {
        toast((e as Error).message, "bad");
        return created;
      }
    },
    onSuccess: (x) => {
      void qc.invalidateQueries({ queryKey: ["finance"] });
      toast(x.status === "posted" ? t("expenses.posted") : x.status === "pending_approval" ? t("expenses.sent") : t("expenses.savedDraft"), "ok");
      onClose();
      navigate(`/finance/expenses/${x.id}`);
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });

  const valid = !!f.values.description.trim() && !!f.values.account_id && Number(f.values.amount) > 0 && Number(f.values.tax_amount || 0) <= Number(f.values.amount);
  return (
    <Drawer open onClose={onClose} title={t("expenses.new")}
      footer={<>
        <Button variant="secondary" disabled={!valid || save.isPending} loading={save.isPending && save.variables === false} onClick={() => save.mutate(false)}>{t("expenses.saveDraft")}</Button>
        <Button disabled={!valid || save.isPending} loading={save.isPending && save.variables === true} onClick={() => save.mutate(true)}>{t("expenses.saveSubmit")}</Button>
      </>}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (valid && !save.isPending) save.mutate(true); }}>
        <Field label={t("description")} required error={f.error("description")}><Input {...f.bind("description")} maxLength={500} required autoFocus placeholder={t("expenses.descriptionExample")} /></Field>
        <Field label={t("expenses.category")} required error={f.error("account_id")} hint={t("expenses.categoryHint")}>
          <Combobox value={f.values.account_id} onChange={(v) => f.set("account_id", v)} options={accountOptions(accounts.data, { types: ["expense"], postable: true })} placeholder={t("expenses.chooseCategory")} />
        </Field>
        <FormGrid>
          <Field label={t("amount")} required error={f.error("amount")} hint={t("expenses.amountHint")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} required /></Field>
          <Field label={t("expenses.taxAmount")} error={f.error("tax_amount")} hint={t("expenses.taxHint")}><NumberInput value={f.values.tax_amount} onChange={(v) => f.set("tax_amount", v)} /></Field>
          <Field label={t("date")} required error={f.error("expense_date")}><Input type="date" {...f.bind("expense_date")} required /></Field>
          <Field label={t("expenses.paidFrom")} required error={f.error("paid_from")}>
            <Select {...f.bind("paid_from")}>{PAID_FROM.map((p) => <option key={p} value={p}>{t(`paidFrom.${p}`)}</option>)}</Select>
          </Field>
          {scope.branches.length > 1 && (
            <Field label={t("branch")} error={f.error("branch_id")}>
              <Select {...f.bind("branch_id")}><option value="">{t("noBranch")}</option>{scope.branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select>
            </Field>
          )}
          <Field label={t("expenses.payee")} error={f.error("payee")}><Input {...f.bind("payee")} maxLength={200} /></Field>
        </FormGrid>
        <Field label={t("expenses.receipt")} error={f.error("receipt_ref")} hint={t("expenses.receiptHint")}><Input {...f.bind("receipt_ref")} maxLength={100} /></Field>
      </form>
    </Drawer>
  );
}
