import { useEffect, useState } from "react";

import {
  api, Alert, Button, Field, Input, Modal, money, NumberInput, Select, Textarea, toast, unwrap, useCurrency, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

const METHODS = ["cash", "mobile_money", "bank", "card", "cheque", "other"] as const;

/** Take a payment against what a member owes; afterwards shows the receipt number. */
export function TakePaymentDialog({ open, onClose, memberId, companyId, owed }: { open: boolean; onClose: () => void; memberId: string; companyId: string; owed: string }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const currency = useCurrency(companyId);
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<(typeof METHODS)[number]>("cash");
  const [reference, setReference] = useState("");
  const [receipt, setReceipt] = useState<string | null>(null);
  useEffect(() => { if (open) { setAmount(owed); setMethod("cash"); setReference(""); setReceipt(null); } }, [open, owed]);
  const pay = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/members/{member_id}/payments", { params: { path: { member_id: memberId } }, body: { amount, method, reference: reference.trim() || null } })),
    onSuccess: (r) => { setReceipt(r.receipt_number); void qc.invalidateQueries({ queryKey: ["memberships"] }); toast(t("pay.done"), "ok"); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <Modal open={open} onClose={onClose} title={t("pay.title")} size="sm"
      footer={receipt
        ? <Button onClick={onClose}>{t("pay.close")}</Button>
        : <><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button loading={pay.isPending} disabled={!(Number(amount) > 0)} onClick={() => pay.mutate()}>{t("pay.take")}</Button></>}>
      {receipt ? (
        <div className="space-y-2 text-center">
          <p className="text-sm text-muted">{t("pay.receipt")}</p>
          <p className="font-mono text-3xl font-bold">{receipt}</p>
          <p className="text-sm">{money(amount, currency)} · {t(`pay.methods.${method}`)}</p>
        </div>
      ) : (
        <div className="space-y-4">
          {Number(owed) > 0 && <Alert tone="info">{t("pay.owes", { amount: money(owed, currency) })}</Alert>}
          <Field label={t("pay.amount")} required><NumberInput value={amount} onChange={setAmount} autoFocus /></Field>
          <Field label={t("pay.method")}>
            <Select value={method} onChange={(e) => setMethod(e.target.value as (typeof METHODS)[number])}>{METHODS.map((x) => <option key={x} value={x}>{t(`pay.methods.${x}`)}</option>)}</Select>
          </Field>
          <Field label={t("pay.reference")} hint={t("pay.referenceHint")}><Input value={reference} maxLength={60} onChange={(e) => setReference(e.target.value)} /></Field>
        </div>
      )}
    </Modal>
  );
}

/** Write an invoice off (credit note) or refund it, whole or part, with a reason from the sales return reasons. */
export function CreditRunDialog({ open, onClose, runId, companyId, outstanding, total }: { open: boolean; onClose: () => void; runId: string; companyId: string; outstanding: string; total: string }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const currency = useCurrency(companyId);
  const [reason, setReason] = useState("");
  const [method, setMethod] = useState<"credit_note" | "cash" | "mobile_money">("credit_note");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => { if (open) { setReason(""); setMethod("credit_note"); setAmount(""); setNote(""); } }, [open]);
  const reasons = useQuery({
    enabled: open, queryKey: ["reason-codes", "sale_return"],
    queryFn: () => unwrap(api.GET("/api/v1/settings/reason-codes", { params: { query: { category: "sale_return" } } })),
  });
  const credit = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/invoice-runs/{run_id}/credit", { params: { path: { run_id: runId } }, body: { reason_code_id: reason, refund_method: method, amount: amount.trim() || null, note: note.trim() } })),
    onSuccess: (r) => { void qc.invalidateQueries({ queryKey: ["memberships"] }); toast(t("credit.done", { number: r.credit_number }), "ok"); onClose(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  return (
    <Modal open={open} onClose={onClose} title={t("credit.title")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button loading={credit.isPending} disabled={!reason || !note.trim()} onClick={() => credit.mutate()}>{t("credit.go")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("credit.explain", { total: money(total, currency), owed: money(outstanding, currency) })}</p>
        <Field label={t("credit.reason")} required>
          <Select value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="">{t("pickReason")}</option>
            {reasons.data?.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </Select>
        </Field>
        <Field label={t("credit.how")} hint={t(`credit.howHint.${method}`)}>
          <Select value={method} onChange={(e) => setMethod(e.target.value as typeof method)}>
            {(["credit_note", "cash", "mobile_money"] as const).map((x) => <option key={x} value={x}>{t(`credit.methods.${x}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("credit.amount")} hint={t("credit.amountHint")}><NumberInput value={amount} onChange={setAmount} /></Field>
        <Field label={t("note")} required><Textarea rows={2} maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
