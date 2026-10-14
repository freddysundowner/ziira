import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import {
  api, Button, Card, ConfirmDialog, DataTable, Drawer, Field, formatDate, Input, money, NumberInput, StatusBadge, toast, today, unwrap, useFormState, useMutation, useQuery,
  useQueryClient, useSession, useTranslation,
} from "@/sdk";

import { approvalState } from "../lib/approval";
import type { Employee, Terms } from "../lib/types";

/** Basic pay history: a change is proposed from a date and someone else approves it. */
export function TermsCard({ employee, currency }: { employee: Employee; currency?: string }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const me = useSession().me?.user_id;
  const [adding, setAdding] = useState(false);
  const [deciding, setDeciding] = useState<{ terms: Terms; approve: boolean } | null>(null);
  const key = ["people", "terms", employee.id];
  const terms = useQuery({ queryKey: key, queryFn: () => unwrap(api.GET("/api/v1/people/employees/{employee_id}/terms", { params: { path: { employee_id: employee.id } } })) });

  const decide = useMutation({
    mutationFn: ({ terms: x, approve }: { terms: Terms; approve: boolean }) => unwrap(api.POST(approve ? "/api/v1/people/terms/{terms_id}/approve" : "/api/v1/people/terms/{terms_id}/reject", { params: { path: { terms_id: x.id } } })),
    onSuccess: (_, v) => { void qc.invalidateQueries({ queryKey: key }); toast(t(v.approve ? "pay.approved" : "pay.rejected"), "ok"); setDeciding(null); },
  });

  return (
    <Card title={t("pay.terms")} description={t("pay.termsHint")} flush actions={<Button size="sm" onClick={() => setAdding(true)}><Plus className="h-3.5 w-3.5" />{t("pay.proposeTerms")}</Button>}>
      <DataTable
        rows={terms.data} loading={terms.isLoading} error={terms.error?.message} onRetry={() => void terms.refetch()} rowKey={(x) => x.id}
        empty={{ title: t("pay.noTerms"), hint: t("pay.noTermsHint") }}
        columns={[
          { header: t("pay.validFrom"), cell: (x) => formatDate(x.valid_from) },
          { header: t("pay.basicPay"), align: "right", cell: (x) => <span className="font-medium">{money(x.basic_pay, currency)}</span> },
          { header: t("pay.validTo"), hideBelow: "sm", cell: (x) => (x.valid_to ? formatDate(x.valid_to) : t("pay.current")) },
          { header: t("status"), cell: (x) => <StatusBadge status={approvalState(x)} /> },
          { header: t("pay.note"), hideBelow: "lg", cell: (x) => x.note ?? "—" },
          {
            header: "", align: "right", cell: (x) => approvalState(x) !== "pending" ? null : x.created_by === me
              ? <span className="text-xs text-muted">{t("pay.needsOther")}</span>
              : <span className="flex justify-end gap-1.5"><Button size="sm" onClick={() => setDeciding({ terms: x, approve: true })}>{t("approve")}</Button><Button size="sm" variant="secondary" onClick={() => setDeciding({ terms: x, approve: false })}>{t("reject")}</Button></span>,
          },
        ]}
      />
      <ProposeTerms open={adding} onClose={() => setAdding(false)} employeeId={employee.id} currency={currency} />
      <ConfirmDialog open={!!deciding} onClose={() => setDeciding(null)} busy={decide.isPending} danger={deciding?.approve === false}
        title={deciding?.approve ? t("pay.approveTerms") : t("pay.rejectTerms")} confirmLabel={deciding?.approve ? t("approve") : t("reject")}
        message={deciding ? t(deciding.approve ? "pay.approveTermsAsk" : "pay.rejectTermsAsk", { amount: money(deciding.terms.basic_pay, currency), date: formatDate(deciding.terms.valid_from), name: employee.full_name }) : ""}
        onConfirm={() => deciding && decide.mutate(deciding)} />
    </Card>
  );
}

function ProposeTerms({ open, onClose, employeeId, currency }: { open: boolean; onClose: () => void; employeeId: string; currency?: string }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const f = useFormState({ basic_pay: "", valid_from: today(), note: "" });
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/people/employees/{employee_id}/terms", { params: { path: { employee_id: employeeId } }, body: { basic_pay: f.values.basic_pay, valid_from: f.values.valid_from, note: f.values.note.trim() || null } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["people", "terms", employeeId] }); toast(t("pay.proposed"), "ok"); f.reset(); onClose(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  return (
    <Drawer open={open} onClose={onClose} title={t("pay.proposeTerms")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="terms-form" loading={save.isPending}>{t("pay.propose")}</Button></>}>
      <form id="terms-form" onSubmit={submit} className="space-y-4">
        <p className="rounded-lg bg-info-soft px-3 py-2 text-sm text-info">{t("pay.proposeInfo")}</p>
        <Field label={`${t("pay.basicPay")}${currency ? ` (${currency})` : ""}`} required error={f.error("basic_pay")}>
          <NumberInput value={f.values.basic_pay} onChange={(v) => f.set("basic_pay", v)} required autoFocus />
        </Field>
        <Field label={t("pay.validFrom")} required error={f.error("valid_from")}><Input type="date" {...f.bind("valid_from")} required /></Field>
        <Field label={t("pay.note")} error={f.error("note")}><Input {...f.bind("note")} maxLength={300} /></Field>
      </form>
    </Drawer>
  );
}
