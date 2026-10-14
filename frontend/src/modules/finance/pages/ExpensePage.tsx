import { Undo2 } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  api, Alert, Button, Card, ConfirmDialog, DetailList, ErrorState, Field, formatDate, humanise, Modal, money, PageHeader, Skeleton, StatusBadge, Textarea, toast, unwrap, useCan,
  useFormState, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { accountNames, useAccounts } from "../api";
import { branchName, useScope } from "../scope";

/** One expense: its facts, and the actions that fit its status (submit a draft, reverse a posted one with a reason). */
export default function ExpensePage() {
  const { t } = useTranslation("finance");
  const { expenseId = "" } = useParams();
  const qc = useQueryClient();
  const scope = useScope();
  const canSubmit = useCan("expenses.submit");
  const canDecide = useCan("expenses.approve");
  const [submitting, setSubmitting] = useState(false);
  const [reversing, setReversing] = useState(false);
  const expense = useQuery({ queryKey: ["finance", "expense", expenseId], queryFn: () => unwrap(api.GET("/api/v1/finance/expenses/{expense_id}", { params: { path: { expense_id: expenseId } } })) });
  const x = expense.data;
  const accounts = useAccounts(x?.company_id ?? "", true);
  const currency = scope.companies.find((c) => c.id === x?.company_id)?.currency;
  const submit = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/finance/expenses/{expense_id}/submit", { params: { path: { expense_id: expenseId } } })),
    onSuccess: (r) => { void qc.invalidateQueries({ queryKey: ["finance"] }); toast(r.status === "posted" ? t("expenses.posted") : t("expenses.sent"), "ok"); setSubmitting(false); },
    onError: () => setSubmitting(false),
  });

  if (expense.error) return <ErrorState title={t("expenses.notFound")} message={expense.error.message} onRetry={() => void expense.refetch()} />;
  if (!x) return <Skeleton className="h-48 w-full" />;
  return (
    <>
      <PageHeader back={{ to: "/finance/expenses", label: t("expenses.title") }} title={x.number}
        description={<span className="flex items-center gap-2">{formatDate(x.expense_date)}<StatusBadge status={x.status} /></span>}
        actions={<>
          {x.status === "draft" && canSubmit && <Button onClick={() => setSubmitting(true)}>{t("expenses.submit")}</Button>}
          {x.status === "posted" && canDecide && <Button variant="danger" onClick={() => setReversing(true)}><Undo2 className="h-4 w-4" />{t("expenses.reverse")}</Button>}
        </>} />
      <div className="space-y-4">
        {x.status === "draft" && <Alert tone="warn">{t("expenses.draftHint")}</Alert>}
        {x.status === "pending_approval" && <Alert tone="warn">{t("expenses.pendingHint")}</Alert>}
        {x.status === "rejected" && <Alert tone="bad">{t("expenses.rejectedHint")}</Alert>}
        {x.status === "reversed" && <Alert tone="bad">{t("expenses.reversedHint", { reason: x.reverse_reason ?? "—" })}</Alert>}
        <Card>
          <DetailList items={[
            { label: t("description"), value: x.description },
            { label: t("amount"), value: <span className="tnum font-semibold">{money(x.amount, currency)}</span> },
            { label: t("expenses.taxAmount"), value: money(x.tax_amount, currency) },
            { label: t("expenses.category"), value: accountNames(accounts.data).get(x.account_id) ?? "…" },
            { label: t("expenses.paidFrom"), value: t(`paidFrom.${x.paid_from}`, humanise(x.paid_from)) },
            { label: t("expenses.payee"), value: x.payee ?? "—" },
            { label: t("branch"), value: x.branch_id ? branchName(scope, x.branch_id) : "—" },
            { label: t("expenses.receipt"), value: x.receipt_ref ?? "—" },
            { label: t("entry.entry"), value: x.entry_id ? <Link className="underline" to={`/finance/journal/${x.entry_id}`}>{t("entry.open")}</Link> : "—" },
          ]} />
        </Card>
      </div>
      <ConfirmDialog open={submitting} onClose={() => setSubmitting(false)} busy={submit.isPending} title={t("expenses.submit")} confirmLabel={t("expenses.submit")}
        message={t("expenses.submitAsk", { amount: money(x.amount, currency) })} onConfirm={() => submit.mutate()} />
      <ReverseExpense open={reversing} onClose={() => setReversing(false)} expenseId={x.id} number={x.number} />
    </>
  );
}

function ReverseExpense({ open, onClose, expenseId, number }: { open: boolean; onClose: () => void; expenseId: string; number: string }) {
  const { t } = useTranslation("finance");
  const qc = useQueryClient();
  const f = useFormState({ reason: "" });
  const reverse = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/finance/expenses/{expense_id}/reverse", { params: { path: { expense_id: expenseId } }, body: { reason: f.values.reason.trim() } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["finance"] }); toast(t("expenses.reversedDone"), "ok"); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  return (
    <Modal open={open} onClose={onClose} title={t("expenses.reverseTitle", { number })} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button variant="danger" loading={reverse.isPending} disabled={!f.values.reason.trim()} onClick={() => reverse.mutate()}>{t("expenses.reverse")}</Button></>}>
      <div className="space-y-3">
        <p className="text-sm text-muted">{t("expenses.reverseHint")}</p>
        <Field label={t("entry.reason")} required error={f.error("reason")}><Textarea {...f.bind("reason")} maxLength={500} autoFocus /></Field>
      </div>
    </Modal>
  );
}
