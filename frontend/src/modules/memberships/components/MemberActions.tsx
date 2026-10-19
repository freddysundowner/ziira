import { CirclePause, CirclePlay, Coins, Scale, Undo2, UserMinus } from "lucide-react";
import { useState } from "react";

import {
  api, Alert, Button, ConfirmDialog, Field, formatDate, Input, Modal, money, NumberInput, Select, Switch, Textarea, toast, today, unwrap, useCan, useCurrency,
  useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { usePlans, type Member } from "../hooks";
import { credits } from "../logic";

type Dialog = "pause" | "resume" | "cancel" | "use" | "adjust" | null;

/** The things a person does to a membership: hold it, resume it, cancel it, spend or adjust its credits. */
export function MemberActions({ member }: { member: Member }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const canManage = useCan("memberships.manage");
  const canAdjust = useCan("memberships.credits");
  const [dialog, setDialog] = useState<Dialog>(null);
  const [resumeOn, setResumeOn] = useState("");
  const [frozen, setFrozen] = useState(false);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [atEnd, setAtEnd] = useState(true);
  const [service, setService] = useState("");
  const [qty, setQty] = useState("1");
  const [amount, setAmount] = useState("");
  const [source, setSource] = useState("");
  const [waive, setWaive] = useState(false);
  const currency = useCurrency(member.company_id);
  const plans = usePlans(dialog === "cancel" ? member.company_id : undefined);
  const plan = plans.data?.find((p) => p.id === member.plan_id);
  const allowance = useQuery({
    enabled: dialog === "pause", queryKey: ["memberships", "allowance", member.id],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/members/{member_id}/freeze-allowance", { params: { path: { member_id: member.id } } })),
  });
  const insideTerm = !!member.term_end && member.term_end > today();
  const exitFee = Number(plan?.early_exit_fee ?? 0);
  const live = member.status === "active" || member.status === "paused" || member.status === "frozen";
  const reasons = useQuery({
    enabled: dialog === "cancel", queryKey: ["reason-codes", "membership_cancel"],
    queryFn: () => unwrap(api.GET("/api/v1/settings/reason-codes", { params: { query: { category: "membership_cancel" } } })),
  });

  const open = (d: Dialog) => {
    setNote(""); setReason(""); setAtEnd(true); setFrozen(false); setResumeOn(""); setService(""); setQty("1"); setAmount(""); setWaive(false);
    setSource(crypto.randomUUID());                       // one id per opening: a double click spends the credits once
    setDialog(d);
  };
  const done = (message: string) => { void qc.invalidateQueries({ queryKey: ["memberships"] }); toast(message, "ok"); setDialog(null); };
  const fail = (e: unknown) => toast((e as Error).message, "bad");
  const path = { params: { path: { member_id: member.id } } };

  const pause = useMutation({ meta: { silent: true }, onError: fail, onSuccess: () => done(t("heldDone")),
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/members/{member_id}/pause", { ...path, body: { resume_on: resumeOn || null, frozen, note: note.trim() || null, waive_fee: waive } })) });
  const resume = useMutation({ meta: { silent: true }, onError: fail, onSuccess: () => done(t("resumedDone")),
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/members/{member_id}/resume", { ...path, body: {} })) });
  const cancel = useMutation({ meta: { silent: true }, onError: fail, onSuccess: () => done(t(atEnd ? "cancelScheduled" : "cancelledDone")),
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/members/{member_id}/cancel", { ...path, body: { reason_code_id: reason || null, note: note.trim() || null, at_period_end: atEnd, waive_exit_fee: waive } })) });
  const undo = useMutation({ meta: { silent: true }, onError: fail, onSuccess: () => done(t("cancelWithdrawn")),
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/members/{member_id}/undo-cancel", path)) });
  const use = useMutation({ meta: { silent: true }, onError: fail,
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/credits/consume", { body: { customer_id: member.customer_id, service_ref: service.trim() || null, quantity: qty || "1", source_type: "manual", source_id: source } })),
    onSuccess: (r) => done(Number(r.remaining) > 0 ? t("usedPart", { covered: credits(r.covered), left: credits(r.remaining) }) : t("usedAll", { covered: credits(r.covered) })) });
  const adjust = useMutation({ meta: { silent: true }, onError: fail, onSuccess: () => done(t("adjusted")),
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/credits/adjust", { body: { holder_type: "membership", holder_id: member.id, quantity: amount, note: note.trim() } })) });

  if (!live) return null;
  return (
    <>
      <div className="flex flex-wrap gap-2">
        {canManage && member.status === "active" && <Button variant="secondary" onClick={() => open("use")}><Coins className="h-4 w-4" />{t("useCredit")}</Button>}
        {canAdjust && <Button variant="secondary" onClick={() => open("adjust")}><Scale className="h-4 w-4" />{t("adjustCredits")}</Button>}
        {canManage && member.status === "active" && <Button variant="secondary" onClick={() => open("pause")}><CirclePause className="h-4 w-4" />{t("hold")}</Button>}
        {canManage && member.status !== "active" && <Button variant="secondary" onClick={() => open("resume")}><CirclePlay className="h-4 w-4" />{t("resume")}</Button>}
        {canManage && member.cancel_at && <Button variant="secondary" onClick={() => undo.mutate()} loading={undo.isPending}><Undo2 className="h-4 w-4" />{t("withdrawCancel")}</Button>}
        {canManage && !member.cancel_at && <Button variant="secondary" onClick={() => open("cancel")}><UserMinus className="h-4 w-4" />{t("cancelMembership")}</Button>}
      </div>

      <Modal open={dialog === "pause"} onClose={() => setDialog(null)} title={t("holdTitle")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setDialog(null)}>{t("cancel")}</Button><Button loading={pause.isPending} onClick={() => pause.mutate()}>{t("hold")}</Button></>}>
        <div className="space-y-4">
          <p className="text-sm text-muted">{t("holdExplain")}</p>
          <Field label={t("resumeOn")} hint={t("resumeOnHint")}><Input type="date" min={today()} value={resumeOn} onChange={(e) => setResumeOn(e.target.value)} /></Field>
          <Switch checked={frozen} onChange={setFrozen} label={t("frozenByUs")} />
          {!frozen && allowance.data && (
            <Alert tone={allowance.data.allowed ? "info" : "warn"}>
              {!allowance.data.allowed ? t("holds.notAllowed")
                : allowance.data.limit === null ? t("holds.noLimit")
                : t("holds.allowance", { left: allowance.data.left ?? 0, limit: allowance.data.limit, used: allowance.data.used })}
              {allowance.data.allowed && Number(allowance.data.fee) > 0 && ` ${t("holds.fee", { amount: money(allowance.data.fee, currency) })}`}
            </Alert>
          )}
          {!frozen && canAdjust && Number(allowance.data?.fee ?? 0) > 0 && <Switch checked={waive} onChange={setWaive} label={t("holds.waiveFee")} />}
          <Field label={t("note")}><Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
        </div>
      </Modal>

      <ConfirmDialog open={dialog === "resume"} onClose={() => setDialog(null)} title={t("resumeTitle")} message={t("resumeExplain")} confirmLabel={t("resume")}
        busy={resume.isPending} onConfirm={() => resume.mutate()} />

      <Modal open={dialog === "cancel"} onClose={() => setDialog(null)} title={t("cancelTitle")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setDialog(null)}>{t("keepMembership")}</Button>
          <Button variant="danger" loading={cancel.isPending} disabled={!reason} onClick={() => cancel.mutate()}>{t("cancelMembership")}</Button></>}>
        <div className="space-y-4">
          <Field label={t("whyLeaving")} required>
            <Select value={reason} onChange={(e) => setReason(e.target.value)}>
              <option value="">{t("pickReason")}</option>
              {reasons.data?.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
            </Select>
          </Field>
          <Field label={t("note")}><Textarea rows={2} maxLength={300} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <Switch checked={atEnd} onChange={setAtEnd} label={t("atPeriodEnd")} />
          <Alert tone="info">{atEnd ? t("atPeriodEndHint") : t("cancelNowHint")}</Alert>
          {plan && plan.notice_days > 0 && <Alert tone="info">{t("cancelTerms.notice", { count: plan.notice_days })}</Alert>}
          {insideTerm && member.term_end && (
            <Alert tone="warn">{exitFee > 0 && !atEnd ? t("cancelTerms.exitFee", { date: formatDate(member.term_end), amount: money(plan?.early_exit_fee, currency) }) : t("cancelTerms.term", { date: formatDate(member.term_end) })}</Alert>
          )}
          {insideTerm && exitFee > 0 && !atEnd && canAdjust && <Switch checked={waive} onChange={setWaive} label={t("cancelTerms.waive")} />}
        </div>
      </Modal>

      <Modal open={dialog === "use"} onClose={() => setDialog(null)} title={t("useCreditTitle")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setDialog(null)}>{t("cancel")}</Button><Button loading={use.isPending} disabled={!(Number(qty) > 0)} onClick={() => use.mutate()}>{t("useCredit")}</Button></>}>
        <div className="space-y-4">
          <p className="text-sm text-muted">{t("useCreditExplain")}</p>
          <Field label={t("serviceName")} hint={t("serviceNameHint")}><Input value={service} maxLength={100} onChange={(e) => setService(e.target.value)} /></Field>
          <Field label={t("howMany")}><NumberInput value={qty} onChange={setQty} /></Field>
        </div>
      </Modal>

      <Modal open={dialog === "adjust"} onClose={() => setDialog(null)} title={t("adjustTitle")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setDialog(null)}>{t("cancel")}</Button>
          <Button loading={adjust.isPending} disabled={!amount.trim() || Number(amount) === 0 || !note.trim()} onClick={() => adjust.mutate()}>{t("adjustCredits")}</Button></>}>
        <div className="space-y-4">
          <p className="text-sm text-muted">{t("adjustExplain")}</p>
          <Field label={t("adjustBy")} hint={t("adjustByHint")} required><NumberInput value={amount} onChange={setAmount} /></Field>
          <Field label={t("whyAdjust")} required><Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
        </div>
      </Modal>
    </>
  );
}
