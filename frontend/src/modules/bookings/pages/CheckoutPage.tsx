import { Printer, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  Alert, api, Badge, Button, Card, ConfirmDialog, DetailList, ErrorState, Field, formatDate, Input, Modal, money, NumberInput, PageHeader, Select, Skeleton, Switch, toast,
  unwrap, useCurrency, useMutation, useQuery, useTranslation,
} from "@/sdk";

import { ClientPicker } from "../desk/ClientPicker";
import { LinesEditor } from "../desk/LinesEditor";
import {
  cleanAmount, type DraftState, draftBody, draftFromCheckout, fillFromServer, hasDiscount, isPositive, settlement, staffOnLines,
} from "../desk/logic";
import { PaymentsPanel, type PayRow, type TenderRow, TIP_METHODS, type TipRow, TipsEditor } from "../desk/PaymentsPanel";
import { useOffers, useRefreshBookings, useResources } from "../hooks";
import type { Checkout } from "../types";

/** One screen from a visit to a paid bill: client, lines, discount, insurer, tips, payments. */
export default function CheckoutPage() {
  const { checkoutId = "" } = useParams();
  const first = useQuery({
    queryKey: ["bookings", "checkout", checkoutId], enabled: !!checkoutId, refetchOnWindowFocus: false,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/checkouts/{checkout_id}", { params: { path: { checkout_id: checkoutId } } })),
  });
  const [view, setView] = useState<Checkout | null>(null);
  const [draft, setDraft] = useState<DraftState | null>(null);
  useEffect(() => {
    if (first.data && !view) { setView(first.data); setDraft(draftFromCheckout(first.data)); }
  }, [first.data, view]);

  if (first.error) return <ErrorState message={first.error.message} onRetry={() => void first.refetch()} />;
  if (!view || !draft) return <div className="space-y-3"><Skeleton className="h-10 w-64" /><Skeleton className="h-64 w-full" /></div>;
  return <Bill view={view} setView={setView} draft={draft} setDraft={(fn) => setDraft((d) => (d ? fn(d) : d))} />;
}

function Bill({ view, setView, draft, setDraft }: { view: Checkout; setView: (c: Checkout) => void; draft: DraftState; setDraft: (fn: (d: DraftState) => DraftState) => void }) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const currency = useCurrency(view.company_id);
  const open = view.status === "open";
  const staff = useResources(view.branch_id);
  const offers = useOffers(view.company_id);
  const reasons = useQuery({
    queryKey: ["bookings", "reasons", "checkout_discount"], staleTime: 5 * 60_000,
    queryFn: () => unwrap(api.GET("/api/v1/settings/reason-codes", { params: { query: { category: "checkout_discount" } } })),
  });

  // --- saving the draft (debounced; the server's totals are always the ones shown)
  const [dirty, setDirty] = useState(false);
  const seq = useRef(0);
  const save = useMutation({
    mutationFn: (v: { seq: number; body: ReturnType<typeof draftBody> }) => unwrap(api.PUT("/api/v1/bookings/checkouts/{checkout_id}", { params: { path: { checkout_id: view.id } }, body: v.body })),
    onSuccess: (co, v) => {
      if (v.seq !== seq.current) return;
      setView(co);
      setDraft((d) => ({ ...d, lines: fillFromServer(d.lines, co) }));
    },
  });
  const edit = (fn: (d: DraftState) => DraftState) => { setDraft(fn); setDirty(true); };
  useEffect(() => {
    if (!dirty || !open) return;
    const id = window.setTimeout(() => {
      setDirty(false);
      if (draft.lines.length === 0) return;
      seq.current += 1;
      save.mutate({ seq: seq.current, body: draftBody(draft) });
    }, 700);
    return () => window.clearTimeout(id);
  }, [dirty, draft, open]); // eslint-disable-line react-hooks/exhaustive-deps
  const pendingSave = dirty || save.isPending;

  const setClient = useMutation({
    mutationFn: (customerId: string | null) => unwrap(api.PUT("/api/v1/bookings/checkouts/{checkout_id}/customer", { params: { path: { checkout_id: view.id } }, body: { customer_id: customerId } })),
    onSuccess: (co) => setView(co),
  });

  // --- payment side
  const [payments, setPayments] = useState<PayRow[]>([]);
  const [tenders, setTenders] = useState<TenderRow[]>([]);
  const [tips, setTips] = useState<TipRow[]>([]);
  const [useDeposit, setUseDeposit] = useState(true);
  const [confirming, setConfirming] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [showPayer, setShowPayer] = useState(!!view.payer_customer_id);
  const [payerLabel, setPayerLabel] = useState<string | null>(null);

  const paying = payments.filter((p) => isPositive(p.amount));
  const tendering = tenders.filter((p) => isPositive(p.amount) && p.kind);
  const tipping = tips.filter((p) => isPositive(p.amount) && p.resource_id);
  const settled = settlement(view.totals.total, [...paying.map((p) => p.amount), ...tendering.map((p) => p.amount)]);
  const heldDeposit = Number(view.deposit_held) > 0;
  const needsReason = hasDiscount(draft);
  const reasonMissing = needsReason && !draft.discount_reason_id;
  const blocked = pendingSave || reasonMissing || draft.lines.length === 0 || (settled === "over" && !heldDeposit);

  const complete = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/checkouts/{checkout_id}/complete", {
      params: { path: { checkout_id: view.id } },
      body: {
        payments: paying.map((p) => ({ method: p.method, amount: cleanAmount(p.amount), reference: p.reference.trim() || null })),
        tips: tipping.map((p) => ({ resource_id: p.resource_id, amount: cleanAmount(p.amount), method: p.method })),
        tenders: tendering.map((p) => ({ kind: p.kind, amount: cleanAmount(p.amount), code: p.code.trim() || null })),
        use_deposit: useDeposit,
      },
    })),
    onSuccess: (co) => { setView(co); setConfirming(false); toast(t("checkout.paidToast", { number: co.invoice_number ?? co.number }), "ok"); void refresh(); window.scrollTo({ top: 0 }); },
    onError: () => setConfirming(false),
  });
  const submit = () => { if (settled === "short" && !heldDeposit) setConfirming(true); else complete.mutate(); };

  const header = (
    <PageHeader back={{ to: "/front-desk", label: t("checkout.backToDesk") }} title={t("checkout.title", { number: view.number })}
      description={view.client_name ?? t("checkout.noClient")}
      actions={open ? <SaveState saving={pendingSave} error={save.isError} /> : <Badge tone={view.status === "done" ? "ok" : "neutral"}>{t(`checkout.status.${view.status}`)}</Badge>} />
  );

  if (!open) return <>{header}<DoneView view={view} setView={setView} currency={currency} staff={staff.data ?? []} /></>;

  return (
    <>
      {header}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="space-y-5">
          <Card title={t("checkout.client")}>
            <ClientPicker companyId={view.company_id} value={view.customer_id ?? ""} label={view.client_name}
              onChange={(id) => setClient.mutate(id || null)} />
            {!view.customer_id && <p className="mt-2 text-xs text-muted">{t("checkout.walkInClient")}</p>}
          </Card>

          <Card title={t("checkout.linesTitle")}>
            <LinesEditor lines={draft.lines} onChange={(lines) => edit((d) => ({ ...d, lines }))} served={view.lines} hasClient={!!view.customer_id}
              staff={staff.data ?? []} offers={offers.data ?? []} companyId={view.company_id} branchId={view.branch_id} currency={currency} />
          </Card>

          <Card title={t("checkout.discountTitle")}>
            <div className="grid gap-3 sm:grid-cols-[9rem_8rem_1fr]">
              <Field label={t("checkout.discountKind")}>
                <Select value={draft.discount_kind} onChange={(e) => edit((d) => ({ ...d, discount_kind: e.target.value === "percent" ? "percent" : "amount" }))}>
                  <option value="amount">{t("checkout.kindAmount")}</option>
                  <option value="percent">{t("checkout.kindPercent")}</option>
                </Select>
              </Field>
              <Field label={t("checkout.discountValue")}><NumberInput value={draft.discount_value} onChange={(v) => edit((d) => ({ ...d, discount_value: v }))} /></Field>
              <Field label={t("checkout.discountReason")} required={needsReason} error={reasonMissing ? t("checkout.reasonNeeded") : null}>
                <Select value={draft.discount_reason_id} onChange={(e) => edit((d) => ({ ...d, discount_reason_id: e.target.value }))}>
                  <option value="">{t("checkout.pickReason")}</option>
                  {(reasons.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
                </Select>
              </Field>
            </div>
            <Field label={t("checkout.discountNote")} className="mt-3"><Input value={draft.discount_note} maxLength={300} onChange={(e) => edit((d) => ({ ...d, discount_note: e.target.value }))} /></Field>
          </Card>

          <Card title={t("checkout.insurerTitle")} actions={
            <label className="flex items-center gap-2 text-sm">
              <Switch checked={showPayer} label={t("checkout.insurerToggle")} onChange={(v) => { setShowPayer(v); if (!v) { setPayerLabel(null); edit((d) => ({ ...d, payer_customer_id: "", copay_amount: "", preauth_ref: "" })); } }} />
              {t("checkout.insurerToggle")}
            </label>}>
            {showPayer ? (
              <div className="space-y-3">
                <Field label={t("checkout.insurer")}>
                  <ClientPicker companyId={view.company_id} value={draft.payer_customer_id} label={payerLabel ?? (draft.payer_customer_id ? t("checkout.insurerChosen") : null)} allowAdd={false} placeholder={t("checkout.insurerSearch")}
                    onChange={(id, label) => { setPayerLabel(label); edit((d) => ({ ...d, payer_customer_id: id })); }} />
                </Field>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label={t("checkout.copay")} hint={t("checkout.copayHint")}><NumberInput value={draft.copay_amount} onChange={(v) => edit((d) => ({ ...d, copay_amount: v }))} /></Field>
                  <Field label={t("checkout.preauth")}><Input value={draft.preauth_ref} maxLength={80} onChange={(e) => edit((d) => ({ ...d, preauth_ref: e.target.value }))} /></Field>
                </div>
              </div>
            ) : <p className="text-sm text-muted">{t("checkout.insurerOff")}</p>}
          </Card>
        </div>

        <div className="space-y-5">
          {view.warnings.length > 0 && <div className="space-y-2">{view.warnings.map((w) => <Alert key={w} tone="warn">{w}</Alert>)}</div>}
          <Totals view={view} currency={currency} />
          <Card title={t("checkout.tipsTitle")} description={t("checkout.tipsHint")}>
            <TipsEditor tips={tips} onChange={setTips} staff={staff.data ?? []} defaults={staffOnLines(draft.lines)} />
          </Card>
          <PaymentsPanel total={view.totals.total} currency={currency} customerId={view.customer_id} payments={payments} onPayments={setPayments} tenders={tenders} onTenders={setTenders}
            depositHeld={view.deposit_held} useDeposit={useDeposit} onUseDeposit={setUseDeposit} />
          {settled === "over" && !heldDeposit && <Alert tone="bad">{t("checkout.overpaid")}</Alert>}
          {settled === "short" && paying.length + tendering.length > 0 && !heldDeposit && <Alert tone="info">{t("checkout.shortHint")}</Alert>}
          <div className="sticky bottom-0 -mx-1 space-y-2 bg-bg/90 p-1 backdrop-blur">
            <Button size="lg" className="w-full" disabled={blocked} loading={complete.isPending} onClick={submit}>{t("checkout.complete")}</Button>
            <Button variant="ghost" className="w-full" onClick={() => setDiscarding(true)}><Trash2 className="h-4 w-4" />{t("checkout.discard")}</Button>
          </div>
        </div>
      </div>
      <ConfirmDialog open={confirming} onClose={() => setConfirming(false)} busy={complete.isPending} title={t("checkout.shortTitle")} message={t("checkout.shortMessage")}
        confirmLabel={t("checkout.shortConfirm")} onConfirm={() => complete.mutate()} />
      <DiscardDialog open={discarding} onClose={() => setDiscarding(false)} checkoutId={view.id} />
    </>
  );
}

function SaveState({ saving, error }: { saving: boolean; error: boolean }) {
  const { t } = useTranslation("bookings");
  return <span role="status" aria-live="polite" className="text-sm text-muted print:hidden">{saving ? t("checkout.saving") : error ? t("checkout.saveFailed") : t("checkout.saved")}</span>;
}

function Totals({ view, currency }: { view: Checkout; currency?: string }) {
  const { t } = useTranslation("bookings");
  const x = view.totals;
  const row = (label: string, value: string, strong?: boolean, show = true) => show && (
    <div className={`flex items-baseline justify-between gap-3 ${strong ? "border-t border-line pt-3 text-lg font-bold" : "text-sm"}`}>
      <dt className={strong ? "" : "text-muted"}>{label}</dt><dd className="tnum">{money(value, currency)}</dd>
    </div>
  );
  return (
    <Card title={t("checkout.totalsTitle")}>
      <dl className="space-y-2">
        {row(t("checkout.subtotal"), x.subtotal)}
        {row(t("checkout.lineDiscounts"), x.line_discounts, false, isPositive(x.line_discounts))}
        {row(t("checkout.orderDiscount"), x.order_discount, false, isPositive(x.order_discount))}
        {row(t("checkout.creditUsed"), x.credit_value, false, isPositive(x.credit_value))}
        {row(t("checkout.toPay"), x.total, true)}
        {row(t("checkout.depositHeld"), view.deposit_held, false, isPositive(view.deposit_held))}
        {row(t("checkout.creditOnAccount"), view.credit_on_account, false, isPositive(view.credit_on_account))}
      </dl>
    </Card>
  );
}

function DiscardDialog({ open, onClose, checkoutId }: { open: boolean; onClose: () => void; checkoutId: string }) {
  const { t } = useTranslation("bookings");
  const navigate = useNavigate();
  const refresh = useRefreshBookings();
  const [reason, setReason] = useState("");
  const discard = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/checkouts/{checkout_id}/discard", { params: { path: { checkout_id: checkoutId } }, body: { reason: reason.trim() } })),
    onSuccess: () => { toast(t("checkout.discarded"), "ok"); void refresh(); onClose(); navigate("/front-desk"); },
  });
  return (
    <Modal open={open} onClose={onClose} title={t("checkout.discardTitle")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("checkout.keepBill")}</Button><Button variant="danger" disabled={!reason.trim()} loading={discard.isPending} onClick={() => discard.mutate()}>{t("checkout.discardConfirm")}</Button></>}>
      <div className="space-y-3">
        <p className="text-sm text-muted">{t("checkout.discardMessage")}</p>
        <Field label={t("checkout.discardReason")} required><Input value={reason} maxLength={300} autoFocus onChange={(e) => setReason(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

/** A finished (or thrown away) bill: read only, a receipt to print, and a tip that comes later. */
function DoneView({ view, setView, currency, staff }: { view: Checkout; setView: (c: Checkout) => void; currency?: string; staff: readonly { id: string; name: string }[] }) {
  const { t } = useTranslation("bookings");
  const navigate = useNavigate();
  const refresh = useRefreshBookings();
  const [tipOpen, setTipOpen] = useState(false);
  const [tip, setTip] = useState<TipRow>({ key: "later", resource_id: "", amount: "", method: "cash" });
  const nameOf = (id: string | null) => staff.find((s) => s.id === id)?.name ?? "—";
  const addTip = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/checkouts/{checkout_id}/tips", { params: { path: { checkout_id: view.id } }, body: { resource_id: tip.resource_id, amount: cleanAmount(tip.amount), method: tip.method } })),
    onSuccess: (co) => { setView(co); setTipOpen(false); setTip({ ...tip, amount: "" }); toast(t("checkout.tipAdded"), "ok"); void refresh(); },
  });
  const done = view.status === "done";
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      {!done && <Alert tone="info">{t("checkout.wasDiscarded")}</Alert>}
      <Card className="print:border-0 print:shadow-none">
        <div className="space-y-4">
          <DetailList items={[
            { label: t("checkout.receipt.number"), value: view.invoice_number ?? view.number },
            { label: t("checkout.client"), value: view.client_name ?? t("checkout.noClient") },
            ...(view.completed_at ? [{ label: t("checkout.receipt.when"), value: formatDate(view.completed_at) }] : []),
          ]} />
          <ul className="divide-y divide-line">
            {view.lines.map((l) => (
              <li key={l.id} className="flex items-baseline justify-between gap-3 py-2 text-sm">
                <span className="min-w-0 truncate">{l.description}{Number(l.quantity) !== 1 && ` × ${l.quantity}`}</span>
                <span className="tnum shrink-0">{money(l.net, currency)}</span>
              </li>
            ))}
          </ul>
          <dl className="space-y-1.5 border-t border-line pt-3 text-sm">
            <div className="flex justify-between"><dt className="text-muted">{t("checkout.toPay")}</dt><dd className="tnum font-bold">{money(view.totals.total, currency)}</dd></div>
            {view.payments.map((p) => (
              <div key={p.id} className="flex justify-between"><dt className="text-muted">{p.kind === "deposit" ? t("checkout.depositUsed") : t(`checkout.methods.${p.method}`, p.method)}{p.reference && ` · ${p.reference}`}</dt><dd className="tnum">{money(p.amount, currency)}</dd></div>
            ))}
            <div className="flex justify-between border-t border-line pt-2 text-base font-bold"><dt>{t("checkout.receipt.paid")}</dt><dd className="tnum">{money(view.paid_total, currency)}</dd></div>
            {isPositive(view.tip_total) && <div className="flex justify-between"><dt className="text-muted">{t("checkout.tipsTitle")}</dt><dd className="tnum">{money(view.tip_total, currency)}</dd></div>}
            {view.tips.map((p) => <div key={p.id} className="flex justify-between text-xs text-muted"><dt>{nameOf(p.resource_id)}</dt><dd className="tnum">{money(p.amount, currency)}</dd></div>)}
          </dl>
          {view.payer_invoice_number && <p className="text-xs text-muted">{t("checkout.receipt.insurerInvoice", { number: view.payer_invoice_number })}</p>}
        </div>
      </Card>
      <div className="flex flex-wrap gap-2 print:hidden">
        <Button size="lg" onClick={() => navigate("/front-desk")}>{t("checkout.backToDesk")}</Button>
        {done && <Button size="lg" variant="secondary" onClick={() => setTipOpen(true)}>{t("checkout.addTipLater")}</Button>}
        {done && <Button size="lg" variant="secondary" onClick={() => window.print()}><Printer className="h-4 w-4" />{t("checkout.print")}</Button>}
      </div>
      <Modal open={tipOpen} onClose={() => setTipOpen(false)} title={t("checkout.addTipLater")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setTipOpen(false)}>{t("checkout.close")}</Button><Button disabled={!tip.resource_id || !isPositive(tip.amount)} loading={addTip.isPending} onClick={() => addTip.mutate()}>{t("checkout.save")}</Button></>}>
        <div className="space-y-3">
          <Field label={t("checkout.tipFor")}>
            <Select value={tip.resource_id} onChange={(e) => setTip({ ...tip, resource_id: e.target.value })}>
              <option value="">{t("checkout.pickStaff")}</option>
              {staff.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          </Field>
          <Field label={t("checkout.amount")}><NumberInput value={tip.amount} onChange={(v) => setTip({ ...tip, amount: v })} /></Field>
          <Field label={t("checkout.method")}>
            <Select value={tip.method} onChange={(e) => setTip({ ...tip, method: e.target.value as TipRow["method"] })}>
              {TIP_METHODS.map((m) => <option key={m} value={m}>{t(`checkout.methods.${m}`)}</option>)}
            </Select>
          </Field>
        </div>
      </Modal>
    </div>
  );
}
