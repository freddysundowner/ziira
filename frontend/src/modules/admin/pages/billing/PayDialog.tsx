import { useEffect, useRef, useState } from "react";

import { api, Alert, Button, Field, Input, Modal, money, Spinner, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import { type Attempt, firstOwed, type Invoice, payBody, payerComplete, type PayOption, payPhase, PLAN_KEY, POLL_MS, returnParams, secondsLeft, STATUS_KEY } from "./lib";

const INVOICES_KEY = ["billing-invoices"];

/** Pay one invoice: choose how (when several fit), type what the method needs, confirm the amount, then follow the payment until the provider confirms it. */
export function PayDialog({ invoice, onClose, resume }: { invoice: Invoice; onClose: () => void; resume?: string }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [attemptId, setAttemptId] = useState<string | null>(resume ?? null);
  const options = useQuery({
    queryKey: ["billing-pay-options", invoice.id],
    queryFn: () => unwrap(api.GET("/api/v1/billing/pay/options", { params: { query: { invoice_id: invoice.id } } })),
    enabled: !attemptId,
  });
  const done = () => {
    void qc.invalidateQueries({ queryKey: PLAN_KEY });
    void qc.invalidateQueries({ queryKey: STATUS_KEY });
    void qc.invalidateQueries({ queryKey: INVOICES_KEY });
  };
  const amount = money(invoice.balance, invoice.currency.trim());
  return (
    <Modal open onClose={onClose} title={t("billing.pay.title", { number: invoice.number ?? "" })}>
      {attemptId ? <PaymentProgress attemptId={attemptId} onRetry={() => setAttemptId(null)} onPaid={done} onClose={onClose} />
        : options.error ? <Alert tone="bad">{options.error.message}</Alert>
        : !options.data ? <div className="flex justify-center p-6"><Spinner /></div>
        : <Choose invoice={invoice} amount={amount} options={options.data.options} hints={options.data.hints} instructions={options.data.payment_instructions} onStarted={(a) => setAttemptId(a.id)} onClose={onClose} />}
    </Modal>
  );
}

function Choose({ invoice, amount, options, hints, instructions, onStarted, onClose }: {
  invoice: Invoice; amount: string; options: PayOption[]; hints: string[]; instructions: string; onStarted: (a: Attempt) => void; onClose: () => void;
}) {
  const { t } = useTranslation("kernel");
  const [picked, setPicked] = useState(options.find((o) => o.preferred)?.provider ?? options[0]?.provider);
  const [values, setValues] = useState<Record<string, string>>({});
  const option = options.find((o) => o.provider === picked);
  const start = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/billing/payments", { body: payBody(invoice.id, option!, values) })),
    onSuccess: (a) => {
      if (a.flow === "redirect" && a.redirect_url && a.open) window.location.assign(a.redirect_url);
      else onStarted(a);
    },
    onError: (e: Error) => toast(e.message, "bad"), meta: { silent: true },
  });
  if (!option) {
    return (
      <div className="space-y-3">
        {hints.map((h) => <Alert key={h} tone="warn">{h}</Alert>)}
        <p className="text-sm font-medium">{t("billing.pay.manual")}</p>
        {instructions.trim() && <p className="whitespace-pre-line text-sm text-muted">{instructions}</p>}
        <div className="flex justify-end"><Button variant="secondary" onClick={onClose}>{t("close")}</Button></div>
      </div>
    );
  }
  return (
    <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (payerComplete(option, values)) start.mutate(); }}>
      <p className="text-sm">{t("billing.pay.amount", { amount })}</p>
      {options.length > 1 && (
        <div role="radiogroup" aria-label={t("billing.pay.method")} className="grid gap-2 sm:grid-cols-2">
          {options.map((o) => (
            <button key={o.provider} type="button" role="radio" aria-checked={o.provider === picked} onClick={() => setPicked(o.provider)}
              className={`rounded-lg border px-3 py-2 text-left text-sm font-medium ${o.provider === picked ? "border-brand bg-brand-soft/30" : "border-line hover:bg-sunken"}`}>{o.label}</button>
          ))}
        </div>
      )}
      {option.payer_fields.map((f) => (
        <Field key={f.name} label={f.label} hint={f.help} required={f.required}>
          <Input type={f.kind === "tel" ? "tel" : f.kind === "email" ? "email" : "text"} inputMode={f.kind === "tel" ? "tel" : undefined} autoComplete={f.kind === "tel" ? "tel" : f.kind === "email" ? "email" : "off"}
            value={values[f.name] ?? ""} maxLength={254} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
        </Field>
      ))}
      <p className="text-xs text-muted">{option.flow === "prompt" ? t("billing.pay.promptHint") : t("billing.pay.redirectHint")}</p>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button type="submit" loading={start.isPending} disabled={!payerComplete(option, values)}>{t("billing.pay.confirm", { amount })}</Button>
      </div>
    </form>
  );
}

/** Follows an attempt: reads our own API every few seconds (the server asks the provider; the browser never decides that money arrived). */
export function PaymentProgress({ attemptId, onRetry, onPaid, onClose }: { attemptId: string; onRetry: () => void; onPaid: () => void; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const started = useRef(Date.now());
  const [now, setNow] = useState(Date.now());
  const attempt = useQuery({
    queryKey: ["billing-attempt", attemptId],
    queryFn: () => unwrap(api.GET("/api/v1/billing/payments/{attempt_id}", { params: { path: { attempt_id: attemptId } } })),
    refetchInterval: (q) => (q.state.data && !q.state.data.open ? false : POLL_MS),
  });
  const again = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/billing/payments/{attempt_id}/check", { params: { path: { attempt_id: attemptId } } })),
    onSuccess: (a) => { started.current = Date.now(); void attempt.refetch(); if (a.status === "completed") onPaid(); },
    onError: (e: Error) => toast(e.message, "bad"), meta: { silent: true },
  });
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(id); }, []);
  const a = attempt.data;
  const status = a?.status;
  useEffect(() => { if (status === "completed") onPaid(); }, [status]); // eslint-disable-line react-hooks/exhaustive-deps
  if (attempt.error) return <Alert tone="bad">{attempt.error.message}</Alert>;
  if (!a) return <div className="flex justify-center p-6"><Spinner /></div>;
  const left = secondsLeft(started.current, now);
  const phase = payPhase(a, left);
  const amount = money(a.amount, a.currency.trim());
  return (
    <div className="space-y-4" aria-live="polite">
      {phase === "waiting" && (
        <>
          <div className="flex items-center gap-3"><Spinner /><p className="font-medium">{a.flow === "prompt" ? t("billing.pay.checkPhone") : t("billing.pay.waitingProvider")}</p></div>
          {a.flow === "prompt" && <p className="text-sm text-muted">{t("billing.pay.countdown", { seconds: left, amount })}</p>}
          {a.flow === "redirect" && a.redirect_url && <Button variant="secondary" onClick={() => window.location.assign(a.redirect_url!)}>{t("billing.pay.openPage")}</Button>}
        </>
      )}
      {phase === "paid" && (
        <>
          <Alert tone="ok">{t("billing.pay.paid", { amount, reference: a.payment_reference ?? "" })}</Alert>
          <div className="flex justify-end"><Button onClick={onClose}>{t("billing.pay.done")}</Button></div>
        </>
      )}
      {(phase === "failed" || phase === "expired") && (
        <>
          <Alert tone="bad">{a.result_desc || t("billing.pay.failed")}</Alert>
          <div className="flex justify-end gap-2"><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button onClick={onRetry}>{t("billing.pay.tryAgain")}</Button></div>
        </>
      )}
      {phase === "mismatch" && (
        <>
          <Alert tone="warn">{t("billing.pay.mismatch")}</Alert>
          <div className="flex justify-end"><Button variant="secondary" onClick={onClose}>{t("close")}</Button></div>
        </>
      )}
      {phase === "timeout" && (
        <>
          <Alert tone="warn">{t("billing.pay.timeout")}</Alert>
          <div className="flex justify-end gap-2"><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button loading={again.isPending} onClick={() => again.mutate()}>{t("billing.pay.checkAgain")}</Button></div>
        </>
      )}
    </div>
  );
}

/** The page's "return from the provider" handling: `?attempt=` opens the progress view for that payment (the server decides if it was paid). */
export function ReturnedPayment({ search, onClose }: { search: string; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const back = returnParams(search);
  if (!back) return null;
  return (
    <Modal open onClose={onClose} title={t("billing.pay.returnTitle")}>
      {back.payment === "cancelled" && <Alert tone="info" className="mb-3">{t("billing.pay.cancelledReturn")}</Alert>}
      <PaymentProgress attemptId={back.attempt} onRetry={onClose} onClose={onClose}
        onPaid={() => { void qc.invalidateQueries({ queryKey: PLAN_KEY }); void qc.invalidateQueries({ queryKey: STATUS_KEY }); void qc.invalidateQueries({ queryKey: INVOICES_KEY }); }} />
    </Modal>
  );
}

export { firstOwed };
