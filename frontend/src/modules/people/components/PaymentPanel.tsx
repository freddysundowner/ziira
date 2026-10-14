import { Eye, Mail, MessageSquare } from "lucide-react";
import { useState } from "react";

import { Alert, api, Button, Card, ConfirmDialog, DataTable, money, toast, unwrap, useMutation, useTranslation } from "@/sdk";

import type { PaymentRow, Run } from "../lib/types";
import { DownloadButton } from "./DownloadButton";

/** Paying the run: the bank upload file (full account numbers, every download is audited) and the payslips by email or SMS. */
export function PaymentPanel({ run, currency }: { run: Run; currency?: string }) {
  const { t } = useTranslation("people");
  const [channel, setChannel] = useState<"email" | "sms" | null>(null);
  const list = useMutation({
    meta: { silent: true },
    mutationFn: async () => (await unwrap(api.GET("/api/v1/people/payroll-runs/{run_id}/payment-file", { params: { path: { run_id: run.id }, query: { format: "json" } } }))) as PaymentRow[],
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const send = useMutation({
    mutationFn: (c: "email" | "sms") => unwrap(api.POST("/api/v1/people/payroll-runs/{run_id}/send-payslips", { params: { path: { run_id: run.id } }, body: { channel: c } })),
    onSuccess: () => setChannel(null),
  });

  return (
    <div className="space-y-4">
      <Card title={t("payment.file")} description={t("payment.fileHint")} actions={<>
        <Button variant="secondary" loading={list.isPending} onClick={() => list.mutate()}><Eye className="h-4 w-4" />{t("payment.show")}</Button>
        <DownloadButton fileName={`salary-payments-${run.id}.csv`} request={() => api.GET("/api/v1/people/payroll-runs/{run_id}/payment-file", { params: { path: { run_id: run.id }, query: { format: "csv" } }, parseAs: "blob" })}>{t("payment.download")}</DownloadButton>
      </>} flush={!!list.data}>
        {!list.data ? <p className="text-sm text-muted">{t("payment.audited")}</p> : (
          <DataTable rows={list.data} rowKey={(r) => r.employee_no} empty={{ title: t("payment.empty") }}
            columns={[
              { header: t("employee.fullName"), cell: (r) => <span className="font-medium">{r.name}<span className="ml-2 font-mono text-xs font-normal text-muted">{r.employee_no}</span></span> },
              { header: t("bank.method"), hideBelow: "sm", cell: (r) => t(`bank.methods.${r.method}`, r.method) },
              { header: t("bank.name"), hideBelow: "md", cell: (r) => r.bank_name || "—" },
              { header: t("bank.account"), cell: (r) => <span className="font-mono text-xs">{r.account_no || t("payment.noAccount")}</span> },
              { header: t("amount"), align: "right", cell: (r) => <span className="font-semibold">{money(r.amount, currency)}</span> },
            ]} />
        )}
      </Card>
      <Card title={t("payment.send")} description={t("payment.sendHint")}>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => setChannel("email")}><Mail className="h-4 w-4" />{t("payment.byEmail")}</Button>
          <Button variant="secondary" onClick={() => setChannel("sms")}><MessageSquare className="h-4 w-4" />{t("payment.bySms")}</Button>
        </div>
        {send.data && (
          <Alert tone={send.data.without_contact > 0 ? "warn" : "ok"} className="mt-3">
            {t("payment.sent", { queued: send.data.queued, already: send.data.already_sent, missing: send.data.without_contact })}
          </Alert>
        )}
      </Card>
      <ConfirmDialog open={!!channel} onClose={() => setChannel(null)} busy={send.isPending} title={t("payment.send")} confirmLabel={t("payment.sendNow")}
        message={channel ? t(channel === "email" ? "payment.emailAsk" : "payment.smsAsk") : ""} onConfirm={() => channel && send.mutate(channel)} />
    </div>
  );
}
