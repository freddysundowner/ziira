import { useEffect, useState } from "react";

import { api, Alert, Button, Field, Input, Modal, money, NumberInput, Select, Textarea, unwrap, useTranslation } from "@/sdk";

import { useClaimAction } from "../hooks";
import { type AnswerRow, answerProblem, canAnswer, toAnswers } from "../lib";
import { ANSWERS, VIAS, type Claim, type Estimate } from "../types";

const nowLocal = () => {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
};

/** Write down the payer's answer received by phone, email, a portal or in person: who, how, when, and what they said about each line. */
export function AnswerDialog({ estimate, claim, currency, onClose }: { estimate: Estimate | null; claim: Claim; currency: string | undefined; onClose: () => void }) {
  const { t } = useTranslation("claims");
  const [rows, setRows] = useState<AnswerRow[]>([]);
  const [who, setWho] = useState("");
  const [via, setVia] = useState("phone");
  const [when, setWhen] = useState(nowLocal());
  const [authority, setAuthority] = useState("");
  const [authorityAmount, setAuthorityAmount] = useState("");
  const [note, setNote] = useState("");
  const [tried, setTried] = useState(false);
  const [key] = useState(() => crypto.randomUUID());
  useEffect(() => {
    if (!estimate) return;
    setRows(estimate.lines.filter(canAnswer).map((l) => ({ lineId: l.id, state: "", amount: "", reason: "" })));
    setWho(claim.assessor_name ?? ""); setVia("phone"); setWhen(nowLocal()); setAuthority(""); setAuthorityAmount(""); setNote(""); setTried(false);
  }, [estimate, claim.assessor_name]);
  const open = estimate?.lines.filter(canAnswer) ?? [];
  const set = (id: string, patch: Partial<AnswerRow>) => setRows((all) => all.map((r) => (r.lineId === id ? { ...r, ...patch } : r)));
  const answers = toAnswers(rows);
  const save = useClaimAction(claim.id, async () => {
    await unwrap(api.POST("/api/v1/claims/estimates/{estimate_id}/responses", { params: { path: { estimate_id: estimate?.id ?? "" }, header: { "Idempotency-Key": key } }, body: {
      by_name: who.trim(), via: via as (typeof VIAS)[number], occurred_at: when ? new Date(when).toISOString() : null, answers,
      note: note.trim() || null, authority_ref: authority.trim() || null, authority_amount: authorityAmount.trim() || null } }));
    return unwrap(api.GET("/api/v1/claims/claims/{claim_id}", { params: { path: { claim_id: claim.id } } }));
  }, { done: t("answer.saved"), onDone: onClose });
  const problem = (l: { id: string; asked_total: string }) => answerProblem(rows.find((r) => r.lineId === l.id) ?? { lineId: l.id, state: "", amount: "", reason: "" }, l.asked_total);
  const submit = () => {
    setTried(true);
    if (!who.trim() || answers.length === 0) return;
    if (open.some((l) => rows.find((r) => r.lineId === l.id)?.state && problem(l))) return;
    save.mutate(undefined);
  };
  return (
    <Modal open={estimate !== null} onClose={onClose} title={t("answer.title", { label: estimate?.label ?? "" })} size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={submit}>{t("answer.save")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("answer.hint")}</p>
        {save.error && <Alert tone="bad">{save.error.message}</Alert>}
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label={t("answer.who")} required error={tried && !who.trim() ? t("answer.whoNeeded") : null}><Input value={who} maxLength={160} onChange={(e) => setWho(e.target.value)} /></Field>
          <Field label={t("answer.via")}>
            <Select value={via} onChange={(e) => setVia(e.target.value)}>{VIAS.map((v) => <option key={v} value={v}>{t(`via.${v}`)}</option>)}</Select>
          </Field>
          <Field label={t("answer.when")}><Input type="datetime-local" value={when} max={nowLocal()} onChange={(e) => setWhen(e.target.value)} /></Field>
        </div>
        <div className="flex justify-end">
          <Button size="sm" variant="ghost" onClick={() => setRows((all) => all.map((r) => ({ ...r, state: r.state || "approved" })))}>{t("answer.approveAll")}</Button>
        </div>
        <ul className="space-y-3">
          {open.map((l) => {
            const r = rows.find((x) => x.lineId === l.id);
            if (!r) return null;
            const p = tried && r.state ? problem(l) : null;
            return (
              <li key={l.id} className="rounded-xl border border-line p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium">{l.description}</span>
                  <span className="tnum text-sm text-muted">{t("answer.asked", { amount: money(l.asked_total, currency) })}</span>
                </div>
                <div className="mt-2 grid gap-2 sm:grid-cols-3">
                  <Select aria-label={t("answer.state")} value={r.state} onChange={(e) => set(l.id, { state: e.target.value })}>
                    <option value="">{t("answer.notYet")}</option>
                    {ANSWERS.map((a) => <option key={a} value={a}>{t(`answer.${a}`)}</option>)}
                  </Select>
                  {r.state === "countered" && (
                    <Field label={t("answer.offers")} error={p === "amount" ? t("answer.amountNeeded") : null}>
                      <NumberInput value={r.amount} inputMode="decimal" invalid={p === "amount"} onChange={(v) => set(l.id, { amount: v })} />
                    </Field>
                  )}
                  {(r.state === "rejected" || r.state === "countered" || r.state === "needs_information") && (
                    <div className="sm:col-span-2">
                      <Field label={r.state === "rejected" ? t("answer.reason") : t("answer.noteLine")} error={p === "reason" ? t("answer.reasonNeeded") : null}>
                        <Input value={r.reason} maxLength={500} invalid={p === "reason"} onChange={(e) => set(l.id, { reason: e.target.value })} />
                      </Field>
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        {tried && answers.length === 0 && <Alert tone="warn">{t("answer.noneChosen")}</Alert>}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t("answer.authority")} hint={t("answer.authorityHint")}><Input value={authority} maxLength={80} onChange={(e) => setAuthority(e.target.value)} /></Field>
          <Field label={t("answer.authorityAmount")}><NumberInput value={authorityAmount} inputMode="decimal" onChange={setAuthorityAmount} /></Field>
        </div>
        <Field label={t("answer.note")}><Textarea maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
