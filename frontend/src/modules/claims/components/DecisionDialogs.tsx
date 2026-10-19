import { useEffect, useState } from "react";

import { api, Alert, Button, Checkbox, Field, Input, Modal, money, NumberInput, Select, Textarea, unwrap, useTranslation } from "@/sdk";

import { useClaimAction } from "../hooks";
import type { Claim, EstimateLine } from "../types";

/** The payer offered less for a line: accept it (and say who carries the difference) or argue it again in the next version. */
export function CounterDialog({ line, claim, currency, onClose }: { line: EstimateLine | null; claim: Claim; currency: string | undefined; onClose: () => void }) {
  const { t } = useTranslation("claims");
  const [accept, setAccept] = useState(true);
  const [carrier, setCarrier] = useState("business");
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [tried, setTried] = useState(false);
  useEffect(() => { if (line) { setAccept(true); setCarrier("business"); setName(claim.insured_name ?? ""); setNote(""); setTried(false); } }, [line, claim.insured_name]);
  const save = useClaimAction(claim.id, () => unwrap(api.POST("/api/v1/claims/lines/{line_id}/counter-decision", { params: { path: { line_id: line?.id ?? "" } }, body: {
    accept, shortfall_to: accept ? (carrier as "customer" | "business") : null, customer_agreed_by: accept && carrier === "customer" ? name.trim() : null, note: note.trim() || null } })),
  { done: accept ? t("counter.acceptedDone") : t("counter.declinedDone"), onDone: onClose });
  const gap = line ? Number(line.asked_total) - Number(line.payer_amount ?? 0) : 0;
  const submit = () => { setTried(true); if (accept && carrier === "customer" && !name.trim()) return; save.mutate(undefined); };
  return (
    <Modal open={line !== null} onClose={onClose} title={t("counter.title", { item: line?.description ?? "" })} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} variant={accept ? "primary" : "secondary"} onClick={submit}>{accept ? t("counter.accept") : t("counter.argue")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm">{t("counter.summary", { asked: money(line?.asked_total, currency), offered: money(line?.payer_amount, currency), gap: money(gap, currency) })}</p>
        <Field label={t("counter.what")}>
          <Select value={accept ? "accept" : "argue"} onChange={(e) => setAccept(e.target.value === "accept")}>
            <option value="accept">{t("counter.optAccept")}</option>
            <option value="argue">{t("counter.optArgue")}</option>
          </Select>
        </Field>
        {accept && (
          <>
            <Field label={t("counter.carrier")} hint={t("counter.carrierHint")}>
              <Select value={carrier} onChange={(e) => setCarrier(e.target.value)}>
                <option value="business">{t("counter.byBusiness")}</option>
                <option value="customer">{t("counter.byCustomer")}</option>
              </Select>
            </Field>
            {carrier === "customer" && (
              <Field label={t("counter.customerName")} required error={tried && !name.trim() ? t("counter.customerNameNeeded") : null} hint={t("counter.customerNameHint")}>
                <Input value={name} maxLength={160} onChange={(e) => setName(e.target.value)} />
              </Field>
            )}
          </>
        )}
        {!accept && <Alert tone="info">{t("counter.argueHint")}</Alert>}
        <Field label={t("counter.note")}><Textarea maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

/** The payer rejected a line: write down whether the customer will pay for it. */
export function CustomerDecisionDialog({ line, claim, currency, onClose }: { line: EstimateLine | null; claim: Claim; currency: string | undefined; onClose: () => void }) {
  const { t } = useTranslation("claims");
  const [pays, setPays] = useState(true);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [tried, setTried] = useState(false);
  useEffect(() => { if (line) { setPays(true); setName(claim.insured_name ?? ""); setNote(""); setTried(false); } }, [line, claim.insured_name]);
  const save = useClaimAction(claim.id, () => unwrap(api.POST("/api/v1/claims/lines/{line_id}/customer-decision", { params: { path: { line_id: line?.id ?? "" } }, body: { pays, by_name: name.trim(), note: note.trim() || null } })),
    { done: pays ? t("customer.paysDone") : t("customer.declinedDone"), onDone: onClose });
  return (
    <Modal open={line !== null} onClose={onClose} title={t("customer.title", { item: line?.description ?? "" })} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => { setTried(true); if (name.trim()) save.mutate(undefined); }}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm">{t("customer.summary", { amount: money(line?.asked_total, currency), reason: line?.payer_reason ?? "" })}</p>
        <Field label={t("customer.what")}>
          <Select value={pays ? "pays" : "declines"} onChange={(e) => setPays(e.target.value === "pays")}>
            <option value="pays">{t("customer.optPays")}</option>
            <option value="declines">{t("customer.optDeclines")}</option>
          </Select>
        </Field>
        <Field label={t("customer.name")} required error={tried && !name.trim() ? t("customer.nameNeeded") : null}><Input value={name} maxLength={160} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label={t("counter.note")}><Textarea maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

/** The payer now pays less for a line that was already invoiced: the invoice lines are credited and the line is billed again. */
export function ReductionDialog({ line, claim, currency, onClose }: { line: EstimateLine | null; claim: Claim; currency: string | undefined; onClose: () => void }) {
  const { t } = useTranslation("claims");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [by, setBy] = useState("");
  const [carrier, setCarrier] = useState("business");
  const [agreed, setAgreed] = useState("");
  const [sure, setSure] = useState(false);
  const [tried, setTried] = useState(false);
  useEffect(() => { if (line) { setAmount(""); setReason(""); setBy(claim.assessor_name ?? ""); setCarrier("business"); setAgreed(claim.insured_name ?? ""); setSure(false); setTried(false); } }, [line, claim.assessor_name, claim.insured_name]);
  const save = useClaimAction(claim.id, () => unwrap(api.POST("/api/v1/claims/claims/{claim_id}/reductions", { params: { path: { claim_id: claim.id } }, body: {
    line_id: line?.id ?? "", new_amount: amount.trim(), reason: reason.trim(), by_name: by.trim(), shortfall_to: carrier as "customer" | "business", customer_agreed_by: carrier === "customer" ? agreed.trim() : null } })),
  { done: t("reduce.done"), onDone: onClose });
  const pays = Number(line?.payer_pays ?? 0);
  const amountBad = amount.trim() === "" || Number(amount) < 0 || Number(amount) >= pays;
  const problem = amountBad || !reason.trim() || !by.trim() || !sure || (carrier === "customer" && Number(amount) > 0 && !agreed.trim());
  return (
    <Modal open={line !== null} onClose={onClose} title={t("reduce.title", { item: line?.description ?? "" })} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => { setTried(true); if (!problem) save.mutate(undefined); }}>{t("reduce.save")}</Button></>}>
      <div className="space-y-4">
        <Alert tone="warn">{t("reduce.warning", { amount: money(pays, currency) })}</Alert>
        <Field label={t("reduce.newAmount")} hint={t("reduce.newAmountHint")} required error={tried && amountBad ? t("reduce.amountBad", { max: money(pays, currency) }) : null}>
          <NumberInput value={amount} inputMode="decimal" invalid={tried && amountBad} onChange={setAmount} />
        </Field>
        <Field label={t("reduce.by")} required error={tried && !by.trim() ? t("reduce.byNeeded") : null}><Input value={by} maxLength={160} onChange={(e) => setBy(e.target.value)} /></Field>
        <Field label={t("reduce.reason")} required error={tried && !reason.trim() ? t("reduce.reasonNeeded") : null}><Input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} /></Field>
        {Number(amount) > 0 && (
          <Field label={t("counter.carrier")}>
            <Select value={carrier} onChange={(e) => setCarrier(e.target.value)}>
              <option value="business">{t("counter.byBusiness")}</option>
              <option value="customer">{t("counter.byCustomer")}</option>
            </Select>
          </Field>
        )}
        {carrier === "customer" && Number(amount) > 0 && (
          <Field label={t("counter.customerName")} required error={tried && !agreed.trim() ? t("counter.customerNameNeeded") : null}><Input value={agreed} maxLength={160} onChange={(e) => setAgreed(e.target.value)} /></Field>
        )}
        <Checkbox label={t("reduce.sure")} checked={sure} onChange={(e) => setSure(e.target.checked)} />
      </div>
    </Modal>
  );
}
