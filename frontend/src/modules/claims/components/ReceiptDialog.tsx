import { useEffect, useState } from "react";

import { api, Alert, Badge, Button, Checkbox, Field, formatDate, Input, Modal, money, NumberInput, Select, today, unwrap, useTranslation } from "@/sdk";

import { useBranchChoice, useClaimsCompany, useClaimsMutation, useOwed } from "../hooks";
import { cents, fromCents } from "../lib";

const METHODS = ["mobile_money", "bank", "cheque", "card", "cash", "other"] as const;

interface Row { runId: string; amount: string; closes: boolean }

/** Money received from a payer (a remittance): which of its invoices it pays, and whether the payer treats an invoice as settled. */
export function ReceiptDialog({ payerId, payerName, claimId, currency, onClose }: { payerId: string | null; payerName: string; claimId?: string; currency: string | undefined; onClose: () => void }) {
  const { t } = useTranslation("claims");
  const { branches } = useClaimsCompany();
  const { branchId, setBranchId } = useBranchChoice(branches);
  const owed = useOwed(payerId ?? "", payerId !== null);
  const [rows, setRows] = useState<Record<string, Row>>({});
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<(typeof METHODS)[number]>("mobile_money");
  const [reference, setReference] = useState("");
  const [day, setDay] = useState(today());
  const [tried, setTried] = useState(false);
  useEffect(() => { if (payerId) { setRows({}); setAmount(""); setReference(""); setDay(today()); setTried(false); } }, [payerId]);
  const list = (owed.data ?? []).filter((o) => !claimId || o.claim_id === claimId || rows[o.run_id]);
  const allocated = Object.values(rows).reduce((n, r) => n + cents(r.amount), 0);
  const toggle = (runId: string, outstanding: string, on: boolean) => setRows((all) => {
    const next = { ...all };
    if (on) next[runId] = { runId, amount: outstanding, closes: false }; else delete next[runId];
    return next;
  });
  const fill = () => setAmount(fromCents(allocated));
  const save = useClaimsMutation(() => unwrap(api.POST("/api/v1/claims/payers/{payer_id}/receipts", { params: { path: { payer_id: payerId ?? "" } }, body: {
    branch_id: branchId, amount: amount.trim(), method, reference: reference.trim() || null, received_on: day || null,
    allocations: Object.values(rows).map((r) => ({ run_id: r.runId, amount: r.amount.trim(), closes_invoice: r.closes })) } })),
  { silent: true, onDone: (r) => { onClose(); void r; } });
  const over = allocated > cents(amount);
  const bad = cents(amount) <= 0 || over || Object.values(rows).some((r) => cents(r.amount) <= 0) || !branchId;
  return (
    <Modal open={payerId !== null} onClose={onClose} title={t("receipt.title", { payer: payerName })} size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => { setTried(true); if (!bad) save.mutate(undefined); }}>{t("receipt.save")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("receipt.hint")}</p>
        {save.error && <Alert tone="bad">{save.error.message}</Alert>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("receipt.amount")} required error={tried && cents(amount) <= 0 ? t("receipt.amountNeeded") : over ? t("receipt.over") : null}>
            <NumberInput value={amount} inputMode="decimal" invalid={tried && (cents(amount) <= 0 || over)} onChange={setAmount} />
          </Field>
          <Field label={t("receipt.method")}><Select value={method} onChange={(e) => setMethod(e.target.value as (typeof METHODS)[number])}>{METHODS.map((m) => <option key={m} value={m}>{t(`receipt.methods.${m}`)}</option>)}</Select></Field>
          <Field label={t("receipt.reference")} hint={t("receipt.referenceHint")}><Input value={reference} maxLength={60} onChange={(e) => setReference(e.target.value)} /></Field>
          <Field label={t("receipt.date")}><Input type="date" value={day} max={today()} onChange={(e) => setDay(e.target.value)} /></Field>
          {branches.length > 1 && (
            <Field label={t("receipt.branch")}><Select value={branchId} onChange={(e) => setBranchId(e.target.value)}>{branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}</Select></Field>
          )}
        </div>
        <div>
          <div className="mb-1 flex items-center justify-between"><h3 className="text-sm font-semibold">{t("receipt.invoices")}</h3>{allocated > 0 && <Button size="sm" variant="ghost" onClick={fill}>{t("receipt.useAllocated", { amount: money(fromCents(allocated), currency) })}</Button>}</div>
          {owed.isLoading && <p className="text-sm text-muted">{t("common.loading")}</p>}
          {list.length === 0 && !owed.isLoading && <p className="rounded-lg bg-sunken px-3 py-3 text-sm text-muted">{t("receipt.noneOwed")}</p>}
          <ul className="space-y-2">
            {list.map((o) => {
              const row = rows[o.run_id];
              return (
                <li key={o.run_id} className="rounded-xl border border-line p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <Checkbox label={<span><span className="font-medium">{o.invoice_number}</span> · {o.claim_number}</span>} checked={!!row} onChange={(e) => toggle(o.run_id, o.outstanding, e.target.checked)} />
                    <span className="tnum text-sm">{t("receipt.owes", { amount: money(o.outstanding, currency) })} {o.days_late > 0 ? <Badge tone="bad">{t("receipt.late", { n: o.days_late })}</Badge> : <span className="text-xs text-muted">{t("receipt.due", { date: formatDate(o.due_date) })}</span>}</span>
                  </div>
                  {row && (
                    <div className="mt-2 grid gap-2 sm:grid-cols-2">
                      <Field label={t("receipt.paysNow")}><NumberInput value={row.amount} inputMode="decimal" onChange={(v) => setRows((all) => ({ ...all, [o.run_id]: { ...row, amount: v } }))} /></Field>
                      <div className="flex items-end"><Checkbox label={t("receipt.closes")} checked={row.closes} onChange={(e) => setRows((all) => ({ ...all, [o.run_id]: { ...row, closes: e.target.checked } }))} /></div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </Modal>
  );
}
