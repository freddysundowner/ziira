import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  api, Button, Card, ConfirmDialog, DataTable, Drawer, Field, formatDate, Input, Select, StatusBadge, toast, unwrap, useFormState, useMutation, useQuery, useQueryClient,
  useSession, useTranslation,
} from "@/sdk";

import { approvalState } from "../lib/approval";
import type { Bank, Employee } from "../lib/types";

/** Where the salary is paid. A new account is proposed by one person and approved by another before payroll uses it. */
export function BankCard({ employee }: { employee: Employee }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const me = useSession().me?.user_id;
  const [adding, setAdding] = useState(false);
  const [deciding, setDeciding] = useState<{ bank: Bank; approve: boolean } | null>(null);
  const key = ["people", "banks", employee.id];
  const banks = useQuery({ queryKey: key, queryFn: () => unwrap(api.GET("/api/v1/people/employees/{employee_id}/bank-accounts", { params: { path: { employee_id: employee.id } } })) });
  const decide = useMutation({
    mutationFn: ({ bank, approve }: { bank: Bank; approve: boolean }) => unwrap(api.POST(approve ? "/api/v1/people/bank-accounts/{bank_id}/approve" : "/api/v1/people/bank-accounts/{bank_id}/reject", { params: { path: { bank_id: bank.id } } })),
    onSuccess: (_, v) => { void qc.invalidateQueries({ queryKey: key }); toast(t(v.approve ? "pay.approved" : "pay.rejected"), "ok"); setDeciding(null); },
  });

  return (
    <Card title={t("bank.title")} description={t("bank.hint")} flush actions={<Button size="sm" onClick={() => setAdding(true)}><Plus className="h-3.5 w-3.5" />{t("bank.propose")}</Button>}>
      <DataTable
        rows={banks.data} loading={banks.isLoading} error={banks.error?.message} onRetry={() => void banks.refetch()} rowKey={(b) => b.id}
        empty={{ title: t("bank.empty"), hint: t("bank.emptyHint") }}
        columns={[
          { header: t("bank.method"), cell: (b) => t(`bank.methods.${b.method}`, b.method) },
          { header: t("bank.name"), hideBelow: "sm", cell: (b) => b.bank_name ?? "—" },
          { header: t("bank.account"), cell: (b) => <span className="font-mono text-xs">{b.account_no_masked ?? "—"}</span> },
          { header: t("pay.validFrom"), hideBelow: "md", cell: (b) => formatDate(b.valid_from) },
          { header: t("pay.validTo"), hideBelow: "lg", cell: (b) => (b.valid_to ? formatDate(b.valid_to) : t("pay.current")) },
          { header: t("status"), cell: (b) => <StatusBadge status={approvalState(b)} /> },
          {
            header: "", align: "right", cell: (b) => approvalState(b) !== "pending" ? null : b.created_by === me
              ? <span className="text-xs text-muted">{t("pay.needsOther")}</span>
              : <span className="flex justify-end gap-1.5"><Button size="sm" onClick={() => setDeciding({ bank: b, approve: true })}>{t("approve")}</Button><Button size="sm" variant="secondary" onClick={() => setDeciding({ bank: b, approve: false })}>{t("reject")}</Button></span>,
          },
        ]}
      />
      <ProposeBank open={adding} onClose={() => setAdding(false)} employeeId={employee.id} />
      <ConfirmDialog open={!!deciding} onClose={() => setDeciding(null)} busy={decide.isPending} danger={deciding?.approve === false}
        title={deciding?.approve ? t("bank.approve") : t("bank.reject")} confirmLabel={deciding?.approve ? t("approve") : t("reject")}
        message={deciding ? t(deciding.approve ? "bank.approveAsk" : "bank.rejectAsk", { account: deciding.bank.account_no_masked ?? "", name: employee.full_name }) : ""}
        onConfirm={() => deciding && decide.mutate(deciding)} />
    </Card>
  );
}

function ProposeBank({ open, onClose, employeeId }: { open: boolean; onClose: () => void; employeeId: string }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const f = useFormState({ method: "bank", account_no: "", bank_name: "" });
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/people/employees/{employee_id}/bank-accounts", { params: { path: { employee_id: employeeId } }, body: {
      method: f.values.method as "bank", account_no: f.values.account_no.trim(), bank_name: f.values.method === "bank" ? f.values.bank_name.trim() || null : null } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["people", "banks", employeeId] }); toast(t("pay.proposed"), "ok"); f.reset(); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Drawer open={open} onClose={onClose} title={t("bank.propose")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="bank-form" loading={save.isPending}>{t("pay.propose")}</Button></>}>
      <form id="bank-form" onSubmit={submit} className="space-y-4">
        <p className="rounded-lg bg-info-soft px-3 py-2 text-sm text-info">{t("bank.proposeInfo")}</p>
        <Field label={t("bank.method")}><Select {...f.bind("method")}><option value="bank">{t("bank.methods.bank")}</option><option value="mobile_money">{t("bank.methods.mobile_money")}</option></Select></Field>
        {f.values.method === "bank" && <Field label={t("bank.name")} error={f.error("bank_name")}><Input {...f.bind("bank_name")} maxLength={100} /></Field>}
        <Field label={f.values.method === "bank" ? t("bank.accountNo") : t("bank.mobileNo")} required error={f.error("account_no")}><Input {...f.bind("account_no")} required autoComplete="off" maxLength={60} /></Field>
      </form>
    </Drawer>
  );
}
