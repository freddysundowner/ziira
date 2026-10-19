import { useState } from "react";

import { api, Alert, Button, Field, Input, Modal, NumberInput, Select, Textarea, unwrap, useTranslation } from "@/sdk";

import { useClaimAction } from "../hooks";
import { CLOSE_REASONS, type Claim } from "../types";

export type ClaimDialog = "authority" | "complete" | "note" | "close" | "work" | "edit" | null;

interface Props { claim: Claim; onClose: () => void }

/** The payer's authority to repair, as told to us by phone, email or letter. */
export function AuthorityDialog({ claim, onClose }: Props) {
  const { t } = useTranslation("claims");
  const [ref, setRef] = useState(claim.authority_ref ?? "");
  const [amount, setAmount] = useState(claim.authority_amount ?? "");
  const [by, setBy] = useState(claim.authority_by ?? "");
  const [tried, setTried] = useState(false);
  const save = useClaimAction(claim.id, () => unwrap(api.PUT("/api/v1/claims/claims/{claim_id}/authority", { params: { path: { claim_id: claim.id } }, body: { reference: ref.trim(), amount: String(amount).trim() || null, by_name: by.trim() || null } })),
    { done: t("authority.saved"), onDone: onClose });
  return (
    <Modal open onClose={onClose} title={t("authority.title")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => { setTried(true); if (ref.trim()) save.mutate(undefined); }}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("authority.hint")}</p>
        <Field label={t("authority.reference")} required error={tried && !ref.trim() ? t("authority.referenceNeeded") : null}><Input value={ref} maxLength={80} onChange={(e) => setRef(e.target.value)} /></Field>
        <Field label={t("authority.amount")}><NumberInput value={String(amount)} inputMode="decimal" onChange={setAmount} /></Field>
        <Field label={t("authority.by")}><Input value={by} maxLength={160} onChange={(e) => setBy(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

/** Sign the work off: the name and time of whoever accepted it. */
export function CompletionDialog({ claim, onClose }: Props) {
  const { t } = useTranslation("claims");
  const [name, setName] = useState(claim.assessor_name ?? claim.insured_name ?? "");
  const [note, setNote] = useState("");
  const [tried, setTried] = useState(false);
  const save = useClaimAction(claim.id, () => unwrap(api.POST("/api/v1/claims/claims/{claim_id}/completion", { params: { path: { claim_id: claim.id } }, body: { signed_by: name.trim(), note: note.trim() || null } })),
    { done: t("complete.saved"), onDone: onClose });
  return (
    <Modal open onClose={onClose} title={t("complete.title")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => { setTried(true); if (name.trim()) save.mutate(undefined); }}>{t("complete.save")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("complete.hint")}</p>
        <Field label={t("complete.name")} required error={tried && !name.trim() ? t("complete.nameNeeded") : null}><Input value={name} maxLength={160} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label={t("complete.note")}><Textarea maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

/** A dated note: a plain note, an assessor's visit or a re-inspection. */
export function NoteDialog({ claim, onClose }: Props) {
  const { t } = useTranslation("claims");
  const [kind, setKind] = useState("note");
  const [text, setText] = useState("");
  const [day, setDay] = useState("");
  const [by, setBy] = useState("");
  const [tried, setTried] = useState(false);
  const save = useClaimAction(claim.id, () => unwrap(api.POST("/api/v1/claims/claims/{claim_id}/notes", { params: { path: { claim_id: claim.id } }, body: {
    kind: kind as "note" | "assessor_visit" | "reinspection", note: text.trim(), occurred_on: day || null, by: by.trim() || null } })),
  { done: t("note.saved"), onDone: onClose });
  return (
    <Modal open onClose={onClose} title={t("note.title")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => { setTried(true); if (text.trim()) save.mutate(undefined); }}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("note.kind")}>
          <Select value={kind} onChange={(e) => setKind(e.target.value)}>
            {["note", "assessor_visit", "reinspection"].map((k) => <option key={k} value={k}>{t(`note.kinds.${k}`)}</option>)}
          </Select>
        </Field>
        {kind !== "note" && <Field label={t("note.day")}><Input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>}
        {kind !== "note" && <Field label={t("note.by")}><Input value={by} maxLength={160} onChange={(e) => setBy(e.target.value)} /></Field>}
        <Field label={t("note.text")} required error={tried && !text.trim() ? t("note.textNeeded") : null}><Textarea maxLength={2000} value={text} onChange={(e) => setText(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

/** Close the claim with an outcome. Total loss, salvage and cash in lieu are outcomes, not separate workflows. */
export function CloseDialog({ claim, onClose }: Props) {
  const { t } = useTranslation("claims");
  const invoiced = claim.runs.length > 0;
  const reasons = invoiced ? ["written_off"] : [...CLOSE_REASONS];
  const [reason, setReason] = useState(reasons[0] ?? "cancelled");
  const [note, setNote] = useState("");
  const [amount, setAmount] = useState("");
  const [tried, setTried] = useState(false);
  const needsNote = ["total_loss", "salvage", "cash_in_lieu", "written_off"].includes(reason);
  const save = useClaimAction(claim.id, () => unwrap(api.POST("/api/v1/claims/claims/{claim_id}/close", { params: { path: { claim_id: claim.id } }, body: { reason: reason as (typeof CLOSE_REASONS)[number], note: note.trim() || null, amount: amount.trim() || null } })),
    { done: t("close.done"), onDone: onClose });
  return (
    <Modal open onClose={onClose} title={t("close.title")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button variant="danger" loading={save.isPending} onClick={() => { setTried(true); if (!needsNote || note.trim()) save.mutate(undefined); }}>{t("close.save")}</Button></>}>
      <div className="space-y-4">
        <Alert tone="warn">{invoiced ? t("close.invoicedHint") : t("close.hint")}</Alert>
        <Field label={t("close.reason")}>
          <Select value={reason} onChange={(e) => setReason(e.target.value)}>{reasons.map((r) => <option key={r} value={r}>{t(`closed.${r}`)}</option>)}</Select>
        </Field>
        {["total_loss", "salvage", "cash_in_lieu"].includes(reason) && <Field label={t("close.amount")} hint={t(`close.amountHint.${reason}`)}><NumberInput value={amount} inputMode="decimal" onChange={setAmount} /></Field>}
        <Field label={t("close.note")} required={needsNote} error={tried && needsNote && !note.trim() ? t("close.noteNeeded") : null}><Textarea maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

/** Go ahead with work the payer has not approved: who decided and why is recorded. */
export function WorkDecisionDialog({ claim, onClose }: Props) {
  const { t } = useTranslation("claims");
  const [note, setNote] = useState("");
  const [tried, setTried] = useState(false);
  const save = useClaimAction(claim.id, () => unwrap(api.POST("/api/v1/claims/claims/{claim_id}/work-decisions", { params: { path: { claim_id: claim.id } }, body: { note: note.trim() } })),
    { done: t("work.saved"), onDone: onClose });
  return (
    <Modal open onClose={onClose} title={t("work.title")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => { setTried(true); if (note.trim()) save.mutate(undefined); }}>{t("work.save")}</Button></>}>
      <div className="space-y-4">
        <Alert tone="warn">{t("work.hint", { amount: claim.gate.unapproved_total })}</Alert>
        <Field label={t("work.why")} required error={tried && !note.trim() ? t("work.whyNeeded") : null}><Textarea maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

/** The claim's own details: policy, claim number, loss, assessor and the excess. */
export function EditDialog({ claim, onClose }: Props) {
  const { t } = useTranslation("claims");
  const [f, setF] = useState({
    subject: claim.subject ?? "", policy: claim.policy_number ?? "", claimNo: claim.claim_number ?? "", member: claim.member_number ?? "", preauth: claim.preauth_ref ?? "",
    loss: claim.loss_date ?? "", lossText: claim.loss_description ?? "", assessor: claim.assessor_name ?? "", assessorPhone: claim.assessor_phone ?? "",
    excess: claim.excess_amount, insured: claim.insured_name ?? "", insuredPhone: claim.insured_phone ?? "",
  });
  const set = (patch: Partial<typeof f>) => setF((x) => ({ ...x, ...patch }));
  const locked = claim.runs.length > 0;
  const save = useClaimAction(claim.id, () => unwrap(api.PATCH("/api/v1/claims/claims/{claim_id}", { params: { path: { claim_id: claim.id } }, body: {
    subject: f.subject.trim() || null, policy_number: f.policy.trim() || null, claim_number: f.claimNo.trim() || null, member_number: f.member.trim() || null,
    preauth_ref: f.preauth.trim() || null, loss_date: f.loss || null, loss_description: f.lossText.trim() || null, assessor_name: f.assessor.trim() || null,
    assessor_phone: f.assessorPhone.trim() || null, insured_name: f.insured.trim() || null, insured_phone: f.insuredPhone.trim() || null,
    ...(locked ? {} : { excess_amount: String(f.excess).trim() || "0" }) } })),
  { done: t("details.saved"), onDone: onClose });
  return (
    <Modal open onClose={onClose} title={t("details.title")} size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => save.mutate(undefined)}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("new.subject")}><Input maxLength={200} value={f.subject} onChange={(e) => set({ subject: e.target.value })} /></Field>
          <Field label={t("new.policy")}><Input maxLength={80} value={f.policy} onChange={(e) => set({ policy: e.target.value })} /></Field>
          <Field label={t("new.claimNo")}><Input maxLength={80} value={f.claimNo} onChange={(e) => set({ claimNo: e.target.value })} /></Field>
          <Field label={t("new.member")}><Input maxLength={80} value={f.member} onChange={(e) => set({ member: e.target.value })} /></Field>
          <Field label={t("new.preauth")}><Input maxLength={80} value={f.preauth} onChange={(e) => set({ preauth: e.target.value })} /></Field>
          <Field label={t("new.loss")}><Input type="date" value={f.loss} onChange={(e) => set({ loss: e.target.value })} /></Field>
          <Field label={t("new.excess")} hint={locked ? t("details.excessLocked") : t("new.excessHint")}><NumberInput value={String(f.excess)} disabled={locked} inputMode="decimal" onChange={(v) => set({ excess: v })} /></Field>
          <Field label={t("details.insured")}><Input maxLength={160} value={f.insured} onChange={(e) => set({ insured: e.target.value })} /></Field>
          <Field label={t("details.insuredPhone")}><Input maxLength={40} type="tel" value={f.insuredPhone} onChange={(e) => set({ insuredPhone: e.target.value })} /></Field>
          <Field label={t("new.assessor")}><Input maxLength={160} value={f.assessor} onChange={(e) => set({ assessor: e.target.value })} /></Field>
          <Field label={t("new.assessorPhone")}><Input maxLength={40} type="tel" value={f.assessorPhone} onChange={(e) => set({ assessorPhone: e.target.value })} /></Field>
        </div>
        <Field label={t("new.lossText")}><Textarea maxLength={2000} value={f.lossText} onChange={(e) => set({ lossText: e.target.value })} /></Field>
      </div>
    </Modal>
  );
}
