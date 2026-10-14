import { Calculator, Check, CircleDollarSign, RotateCcw, Send, XCircle } from "lucide-react";
import { useState } from "react";

import { api, Button, ConfirmDialog, Field, Input, Modal, money, toast, today, unwrap, useCan, useMutation, useQueryClient, useSession, useTranslation } from "@/sdk";

import { type Run, totalsOf } from "../lib/types";

type Step = "calculate" | "submit" | "approve" | "reject" | "cancel" | "pay";

/** The actions a run offers right now: only those its status and the user's permissions allow. Each money-moving step asks first. */
export function RunActions({ run, currency, blockers }: { run: Run; currency?: string; blockers: number }) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const me = useSession().me?.user_id;
  const canPrepare = useCan("payroll.prepare");
  const canApprove = useCan("payroll.approve");
  const canPay = useCan("payroll.pay");
  const [confirm, setConfirm] = useState<Step | null>(null);
  const [note, setNote] = useState("");
  const [paidOn, setPaidOn] = useState(today());
  const id = run.id;

  const act = useMutation({
    mutationFn: (step: Step) => {
      const params = { params: { path: { run_id: id } } };
      switch (step) {
        case "calculate": return unwrap(api.POST("/api/v1/people/payroll-runs/{run_id}/calculate", params));
        case "submit": return unwrap(api.POST("/api/v1/people/payroll-runs/{run_id}/submit", params));
        case "approve": return unwrap(api.POST("/api/v1/people/payroll-runs/{run_id}/approve", params));
        case "cancel": return unwrap(api.POST("/api/v1/people/payroll-runs/{run_id}/cancel", params));
        case "reject": return unwrap(api.POST("/api/v1/people/payroll-runs/{run_id}/reject", { ...params, body: { note: note.trim() } }));
        case "pay": return unwrap(api.POST("/api/v1/people/payroll-runs/{run_id}/pay", { ...params, body: { paid_on: paidOn || null } }));
      }
    },
    onSuccess: (_, step) => {
      void qc.invalidateQueries({ queryKey: ["people", "run", id] });
      void qc.invalidateQueries({ queryKey: ["people", "runs"] });
      toast(t(`run.done.${step}`), "ok");
      setConfirm(null);
      setNote("");
    },
  });
  const close = () => setConfirm(null);
  const own = !!me && run.prepared_by === me;
  const totals = totalsOf(run);
  const s = run.status;

  return (
    <>
      {canPrepare && (s === "draft" || s === "calculated") && (
        <Button variant={s === "draft" ? "primary" : "secondary"} loading={act.isPending && act.variables === "calculate"} onClick={() => act.mutate("calculate")}>
          {s === "draft" ? <Calculator className="h-4 w-4" /> : <RotateCcw className="h-4 w-4" />}{s === "draft" ? t("run.calculate") : t("run.recalculate")}
        </Button>
      )}
      {canPrepare && s === "calculated" && (
        <Button onClick={() => setConfirm("submit")} disabled={blockers > 0} title={blockers > 0 ? t("run.blockedHint") : undefined}><Send className="h-4 w-4" />{t("run.submit")}</Button>
      )}
      {canApprove && s === "pending_approval" && (
        <>
          <Button onClick={() => setConfirm("approve")} disabled={own} title={own ? t("run.ownRun") : undefined}><Check className="h-4 w-4" />{t("run.approve")}</Button>
          <Button variant="secondary" onClick={() => setConfirm("reject")}>{t("run.reject")}</Button>
        </>
      )}
      {canPay && (s === "approved" || s === "posted") && <Button onClick={() => setConfirm("pay")}><CircleDollarSign className="h-4 w-4" />{t("run.pay")}</Button>}
      {canPrepare && (s === "draft" || s === "calculated" || s === "pending_approval") && (
        <Button variant="ghost" onClick={() => setConfirm("cancel")}><XCircle className="h-4 w-4" />{t("run.cancel")}</Button>
      )}

      <ConfirmDialog open={confirm === "submit"} onClose={close} busy={act.isPending} title={t("run.submit")} confirmLabel={t("run.submit")}
        message={t("run.submitAsk", { net: money(totals.net_pay, currency), count: totals.employees ?? 0 })} onConfirm={() => act.mutate("submit")} />
      <ConfirmDialog open={confirm === "approve"} onClose={close} busy={act.isPending} title={t("run.approve")} confirmLabel={t("run.approve")}
        message={t("run.approveAsk", { net: money(totals.net_pay, currency), count: totals.employees ?? 0 })} onConfirm={() => act.mutate("approve")} />
      <ConfirmDialog open={confirm === "cancel"} onClose={close} busy={act.isPending} danger title={t("run.cancel")} confirmLabel={t("run.cancel")}
        message={t("run.cancelAsk")} onConfirm={() => act.mutate("cancel")} />
      <Modal open={confirm === "reject"} onClose={close} size="sm" title={t("run.reject")}
        footer={<><Button variant="secondary" onClick={close}>{t("cancel")}</Button><Button variant="danger" loading={act.isPending} disabled={!note.trim()} onClick={() => act.mutate("reject")}>{t("run.reject")}</Button></>}>
        <p className="mb-3 text-sm text-muted">{t("run.rejectAsk")}</p>
        <Field label={t("run.rejectNote")} required><Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} autoFocus /></Field>
      </Modal>
      <Modal open={confirm === "pay"} onClose={close} size="sm" title={t("run.pay")}
        footer={<><Button variant="secondary" onClick={close}>{t("cancel")}</Button><Button loading={act.isPending} disabled={!paidOn} onClick={() => act.mutate("pay")}>{t("run.payNow")}</Button></>}>
        <p className="mb-3 text-sm text-muted">{t("run.payAsk", { net: money(totals.net_pay, currency), count: totals.employees ?? 0 })}</p>
        <Field label={t("run.paidOn")} required><Input type="date" value={paidOn} min={run.period_start} onChange={(e) => setPaidOn(e.target.value)} /></Field>
      </Modal>
    </>
  );
}
