import { Check } from "lucide-react";
import { useState } from "react";

import { api, Badge, Button, Card, cx, Field, Input, Modal, money, quantity, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { changeRequestBody, intervalsFor, type Invoice, pickPrice, PLAN_KEY, priceCurrency, STATUS_KEY, type MyPlan, type PublicPlan } from "./lib";
import { PayDialog } from "./PayDialog";

const LIMITS = ["max_users", "max_branches", "max_companies"] as const;

/** The plans on offer, side by side. Choosing one opens a confirmation; asking charges nothing. */
export function ChangePlan({ plans, plan, currency }: { plans: PublicPlan[]; plan: MyPlan; currency: string | null | undefined }) {
  const { t } = useTranslation("kernel");
  const [interval, setInterval] = useState<"month" | "year">(plan.interval === "year" ? "year" : "month");
  const [choice, setChoice] = useState<PublicPlan | null>(null);
  const [toPay, setToPay] = useState<Invoice | null>(null);
  const offersYear = plans.some((p) => intervalsFor(p, priceCurrency(p, currency)).includes("year"));
  const offersMonth = plans.some((p) => intervalsFor(p, priceCurrency(p, currency)).includes("month"));
  const locked = !!plan.request;
  return (
    <Card title={t("billing.changeTitle")} description={t("billing.changeHint")}
      actions={offersYear && offersMonth ? (
        <div role="group" aria-label={t("billing.intervalPick")} className="inline-flex rounded-lg border border-line p-0.5 text-sm">
          {(["month", "year"] as const).map((i) => (
            <button key={i} type="button" aria-pressed={interval === i} onClick={() => setInterval(i)}
              className={cx("rounded-md px-3 py-1 font-medium", interval === i ? "bg-brand text-brand-ink" : "text-muted hover:text-ink")}>{t(`billing.intervalName.${i}`)}</button>
          ))}
        </div>
      ) : undefined}>
      {plans.length === 0 ? <p className="text-sm text-muted">{t("billing.noPlans")}</p> : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {plans.map((p) => {
            const cur = priceCurrency(p, currency);
            const price = pickPrice(p, cur, interval);
            const current = p.code === plan.plan_code;
            return (
              <div key={p.code} className={cx("flex flex-col rounded-xl border p-4", current ? "border-brand bg-brand-soft/30" : "border-line")}>
                <div className="flex items-start justify-between gap-2">
                  <h3 className="text-base font-semibold">{p.name}</h3>
                  {current && <Badge tone="brand">{t("billing.currentPlan")}</Badge>}
                </div>
                {p.description && <p className="mt-1 text-sm text-muted">{p.description}</p>}
                <p className="tnum mt-3 text-2xl font-semibold">
                  {price ? money(price.amount, price.currency.trim()) : t("billing.noPrice")}
                  {price && <span className="text-sm font-normal text-muted"> / {t(`billing.interval.${price.interval}`, { defaultValue: price.interval })}</span>}
                </p>
                {price?.tax_inclusive && <p className="text-xs text-muted">{t("billing.taxIncl")}</p>}
                {p.trial_days > 0 && !current && <p className="mt-1 text-xs text-ok">{t("billing.trialDays", { count: p.trial_days })}</p>}
                <ul className="mt-3 space-y-1 text-sm">
                  {LIMITS.filter((k) => k in p.limits).map((k) => (
                    <li key={k} className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden />{t(`billing.limit.${k}`, { value: p.limits[k] === null ? t("billing.unlimited") : quantity(p.limits[k], 0) })}</li>
                  ))}
                  {p.highlights.map((h) => <li key={h} className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-ok" aria-hidden />{h}</li>)}
                </ul>
                <div className="mt-auto pt-4">
                  <Button variant={current ? "secondary" : "primary"} className="w-full" disabled={current || locked || !price} onClick={() => setChoice(p)}>
                    {current ? t("billing.currentPlan") : t("billing.choose")}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {locked && plans.length > 0 && <p className="mt-3 text-sm text-muted">{t("billing.requestLocked")}</p>}
      {choice && <RequestDialog plan={choice} currency={priceCurrency(choice, currency)} interval={interval} onClose={() => setChoice(null)} onInvoice={(i) => { setChoice(null); setToPay(i); }} />}
      {toPay && <PayDialog invoice={toPay} onClose={() => setToPay(null)} />}
    </Card>
  );
}

function RequestDialog({ plan, currency, interval, onClose, onInvoice }: { plan: PublicPlan; currency: string | null; interval: string; onClose: () => void; onInvoice: (i: Invoice) => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [coupon, setCoupon] = useState("");
  const price = pickPrice(plan, currency, interval);
  const send = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/billing/subscribe", { body: changeRequestBody(plan.code, price, coupon, "") })),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: PLAN_KEY });
      void qc.invalidateQueries({ queryKey: STATUS_KEY });
      void qc.invalidateQueries({ queryKey: ["billing-invoices"] });
      if (r.invoice) { onInvoice(r.invoice); return; }
      toast(t("billing.requestDone"), "ok");
      onClose();
    },
    onError: (e: Error) => toast(e.message, "bad"), meta: { silent: true },
  });
  return (
    <Modal open onClose={onClose} title={t("billing.requestTitle", { plan: plan.name })}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button loading={send.isPending} onClick={() => send.mutate()}>{t("billing.subscribeContinue")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm">
          {price ? t("billing.requestSummary", { plan: plan.name, price: money(price.amount, price.currency.trim()), interval: t(`billing.interval.${price.interval}`, { defaultValue: price.interval }) }) : plan.name}
        </p>
        <p className="text-sm text-muted">{t("billing.subscribeExplain")}</p>
        <Field label={t("billing.couponField")}><Input value={coupon} maxLength={40} onChange={(e) => setCoupon(e.target.value)} autoComplete="off" /></Field>
      </div>
    </Modal>
  );
}
