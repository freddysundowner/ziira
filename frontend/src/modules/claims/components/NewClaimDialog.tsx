import { useState } from "react";

import { api, Alert, Button, Field, FormGrid, Input, Modal, NumberInput, Textarea, unwrap, useTranslation } from "@/sdk";

import { useBranchChoice, useClaimsCompany, useClaimsMutation } from "../hooks";
import type { Claim } from "../types";
import { CustomerPicker, PayerSelect } from "./pickers";

export interface ClaimDefaults {
  sourceType?: "job" | "appointment";
  sourceId?: string;
  customerId?: string;
  subject?: string;
  branchId?: string;
  companyId?: string;
}

const blank = (d: ClaimDefaults) => ({
  payerId: "", customerId: d.customerId ?? "", subject: d.subject ?? "", policy: "", claimNo: "", member: "", preauth: "", loss: "",
  lossText: "", assessor: "", assessorPhone: "", excess: "0",
});

/** Open a claim: who pays, for whom, which policy and claim number, the excess. Short, a retry never opens a second claim. */
export function NewClaimDialog({ open, onClose, defaults = {}, onCreated }: { open: boolean; onClose: () => void; defaults?: ClaimDefaults; onCreated: (claim: Claim) => void }) {
  const { t } = useTranslation("claims");
  const own = useClaimsCompany();
  const companyId = defaults.companyId ?? own.companyId;
  const { branchId: chosen } = useBranchChoice(own.branches);
  const [form, setForm] = useState(() => blank(defaults));
  const [tried, setTried] = useState(false);
  const [key] = useState(() => crypto.randomUUID());
  const set = (patch: Partial<ReturnType<typeof blank>>) => setForm((f) => ({ ...f, ...patch }));
  const branchId = defaults.branchId ?? chosen;
  const create = useClaimsMutation(
    () => unwrap(api.POST("/api/v1/claims/claims", { params: { header: { "Idempotency-Key": key } }, body: {
      company_id: companyId, branch_id: branchId || null, payer_id: form.payerId, customer_id: form.customerId || null,
      source_type: defaults.sourceType ?? null, source_id: defaults.sourceId ?? null, subject: form.subject.trim() || null,
      policy_number: form.policy.trim() || null, claim_number: form.claimNo.trim() || null, member_number: form.member.trim() || null,
      preauth_ref: form.preauth.trim() || null, loss_date: form.loss || null, loss_description: form.lossText.trim() || null,
      assessor_name: form.assessor.trim() || null, assessor_phone: form.assessorPhone.trim() || null, excess_amount: form.excess.trim() || "0" } })),
    { silent: true, onDone: (claim) => { setForm(blank(defaults)); setTried(false); onCreated(claim); } });
  const submit = () => { setTried(true); if (form.payerId) create.mutate(undefined); };
  return (
    <Modal open={open} onClose={onClose} title={t("new.title")} size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={create.isPending} onClick={submit}>{t("new.create")}</Button></>}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
        <p className="text-sm text-muted">{defaults.sourceType ? t("new.hintFor", { what: t(`source.${defaults.sourceType}`) }) : t("new.hint")}</p>
        {create.error && <Alert tone="bad">{create.error.message}</Alert>}
        <FormGrid>
          <Field label={t("new.payer")} required error={tried && !form.payerId ? t("new.payerNeeded") : null} hint={t("new.payerHint")}>
            <PayerSelect companyId={companyId} value={form.payerId} onChange={(v) => set({ payerId: v })} invalid={tried && !form.payerId} />
          </Field>
          <Field label={t("new.customer")} hint={t("new.customerHint")}>
            <CustomerPicker value={form.customerId} onChange={(v) => set({ customerId: v })} />
          </Field>
          <Field label={t("new.subject")} hint={t("new.subjectHint")}><Input maxLength={200} value={form.subject} onChange={(e) => set({ subject: e.target.value })} /></Field>
          <Field label={t("new.policy")}><Input maxLength={80} value={form.policy} onChange={(e) => set({ policy: e.target.value })} /></Field>
          <Field label={t("new.claimNo")} hint={t("new.claimNoHint")}><Input maxLength={80} value={form.claimNo} onChange={(e) => set({ claimNo: e.target.value })} /></Field>
          <Field label={t("new.member")} hint={t("new.memberHint")}><Input maxLength={80} value={form.member} onChange={(e) => set({ member: e.target.value })} /></Field>
          <Field label={t("new.preauth")}><Input maxLength={80} value={form.preauth} onChange={(e) => set({ preauth: e.target.value })} /></Field>
          <Field label={t("new.loss")}><Input type="date" value={form.loss} onChange={(e) => set({ loss: e.target.value })} /></Field>
          <Field label={t("new.excess")} hint={t("new.excessHint")}><NumberInput value={form.excess} onChange={(v) => set({ excess: v })} inputMode="decimal" /></Field>
          <Field label={t("new.assessor")}><Input maxLength={160} value={form.assessor} onChange={(e) => set({ assessor: e.target.value })} /></Field>
          <Field label={t("new.assessorPhone")}><Input maxLength={40} type="tel" value={form.assessorPhone} onChange={(e) => set({ assessorPhone: e.target.value })} /></Field>
        </FormGrid>
        <Field label={t("new.lossText")}><Textarea maxLength={2000} value={form.lossText} onChange={(e) => set({ lossText: e.target.value })} /></Field>
      </form>
    </Modal>
  );
}
