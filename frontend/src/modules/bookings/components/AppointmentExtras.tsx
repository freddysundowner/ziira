import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  Alert, api, Button, Modal, Field, FormGrid, Input, money, NumberInput, Select, toast, unwrap, useCan, useCurrency, useMutation, useQuery, useTranslation,
} from "@/sdk";

import { useRefreshBookings, useUnit } from "../hooks";
import type { Appointment } from "../types";

const METHODS = ["cash", "mobile_money", "card", "bank", "other"] as const;

/** Warnings, the deposit, the insurer and the way to the bill for one appointment. */
export function AppointmentExtras({ a, onClient }: { a: Appointment; onClient: () => void }) {
  const { t } = useTranslation("bookings");
  const canCheckout = useCan("bookings.checkout");
  const canManage = useCan("bookings.manage");
  const claimsOn = useUnit("claims");
  const currency = useCurrency(a.company_id);
  const navigate = useNavigate();
  const refresh = useRefreshBookings();
  const [deposit, setDeposit] = useState(false);
  const [claim, setClaim] = useState(false);
  const open = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/checkouts", { body: { appointment_ids: [a.id], local_id: `open-${a.id}` } })),
    onSuccess: (co) => navigate(`/checkout/${co.id}`),
  });
  const due = Number(a.deposit_amount) - Number(a.deposit_paid);
  const billable = ["checked_in", "in_service", "completed"].includes(a.status) && !a.invoice_id && a.kind === "appointment";

  return (
    <div className="space-y-3">
      {a.warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}
      {a.price_variant && <p className="text-xs text-muted">{t("extras.priceFor", { name: a.price_variant })}</p>}
      {a.payer_customer_id && <p className="text-xs text-muted">{t("extras.billedToPayer", { ref: a.preauth_ref ?? "—", copay: a.copay_amount ? money(a.copay_amount, currency) : "—" })}</p>}
      {a.claim_id && <p className="text-xs text-muted">{t("extras.hasClaim")}</p>}
      <div className="flex flex-wrap gap-2">
        {billable && canCheckout && <Button loading={open.isPending} onClick={() => open.mutate()}>{t("extras.checkOut")}</Button>}
        {due > 0 && canCheckout && a.customer_id && ["requested", "confirmed", "checked_in"].includes(a.status) && (
          <Button variant="secondary" onClick={() => setDeposit(true)}>{t("extras.recordDeposit", { amount: money(String(due), currency) })}</Button>
        )}
        {a.customer_id && <Button variant="ghost" onClick={onClient}>{t("extras.clientCard")}</Button>}
        {claimsOn && canManage && a.customer_id && !a.claim_id && a.kind === "appointment" && a.status !== "completed" && (
          <Button variant="ghost" onClick={() => setClaim(true)}>{t("extras.billInsurer")}</Button>
        )}
      </div>
      <DepositDialog a={a} open={deposit} due={due} onClose={() => { setDeposit(false); void refresh(); }} />
      <ClaimDialog a={a} open={claim} onClose={() => { setClaim(false); void refresh(); }} />
    </div>
  );
}

function DepositDialog({ a, open, due, onClose }: { a: Appointment; open: boolean; due: number; onClose: () => void }) {
  const { t } = useTranslation("bookings");
  const [amount, setAmount] = useState(String(due));
  const [method, setMethod] = useState<(typeof METHODS)[number]>("cash");
  const [reference, setReference] = useState("");
  const pay = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/appointments/{appointment_id}/deposit", { params: { path: { appointment_id: a.id } }, body: { amount, method, reference: reference.trim() || null } })),
    onSuccess: () => { toast(t("extras.depositRecorded"), "ok"); onClose(); },
  });
  return (
    <Modal open={open} onClose={onClose} title={t("extras.depositTitle")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button loading={pay.isPending} onClick={() => pay.mutate()} disabled={!(Number(amount) > 0)}>{t("extras.depositSave")}</Button></>}>
      <div className="space-y-3">
        <FormGrid>
          <Field label={t("extras.amount")}><NumberInput value={amount} onChange={setAmount} /></Field>
          <Field label={t("extras.method")}>
            <Select value={method} onChange={(e) => setMethod(e.target.value as (typeof METHODS)[number])}>{METHODS.map((m) => <option key={m} value={m}>{t(`extras.methods.${m}`)}</option>)}</Select>
          </Field>
        </FormGrid>
        <Field label={t("extras.reference")}><Input value={reference} onChange={(e) => setReference(e.target.value)} maxLength={80} /></Field>
        <p className="text-xs text-muted">{t("extras.depositHint")}</p>
      </div>
    </Modal>
  );
}

function ClaimDialog({ a, open, onClose }: { a: Appointment; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("bookings");
  const payers = useQuery({
    queryKey: ["bookings", "claim-payers", a.company_id], enabled: open,
    queryFn: () => unwrap(api.GET("/api/v1/claims/payers", { params: { query: { company_id: a.company_id, only_active: true } } })),
  });
  const [payer, setPayer] = useState("");
  const [policy, setPolicy] = useState("");
  const [member, setMember] = useState("");
  const [pre, setPre] = useState("");
  const make = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/appointments/{appointment_id}/claim", { params: { path: { appointment_id: a.id } }, body: {
      payer_id: payer, policy_number: policy.trim() || null, member_number: member.trim() || null, preauth_ref: pre.trim() || null } })),
    onSuccess: () => { toast(t("extras.claimOpened"), "ok"); onClose(); },
  });
  return (
    <Modal open={open} onClose={onClose} title={t("extras.claimTitle")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button loading={make.isPending} onClick={() => make.mutate()} disabled={!payer}>{t("extras.claimSave")}</Button></>}>
      <div className="space-y-3">
        <Field label={t("extras.payer")}>
          <Select value={payer} onChange={(e) => setPayer(e.target.value)}>
            <option value="">{t("extras.choosePayer")}</option>
            {(payers.data ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </Select>
        </Field>
        {payers.data?.length === 0 && <Alert tone="info">{t("extras.noPayers")}</Alert>}
        <FormGrid>
          <Field label={t("extras.policy")}><Input value={policy} onChange={(e) => setPolicy(e.target.value)} maxLength={80} /></Field>
          <Field label={t("extras.member")}><Input value={member} onChange={(e) => setMember(e.target.value)} maxLength={80} /></Field>
        </FormGrid>
        <Field label={t("extras.preauth")}><Input value={pre} onChange={(e) => setPre(e.target.value)} maxLength={80} /></Field>
        <p className="text-xs text-muted">{t("extras.claimHint")}</p>
      </div>
    </Modal>
  );
}
