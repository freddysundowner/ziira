import { Banknote, CreditCard, Smartphone, Trash2, UserRound } from "lucide-react";

import {
  Alert, api, ApiError, Button, cx, Field, IconButton, Input, Modal, money, NumberInput, unwrap, useCan, useQuery, useSession, useTranslation,
} from "@/sdk";

import { newLeg, type PayLeg, type PayMethod, payProblem, paySummary, text } from "../cart";
import { MobileLeg, type PaymentAccount } from "./MobileLeg";

const METHOD_ICON = { cash: Banknote, card: CreditCard, mobile_money: Smartphone, credit: UserRound, other: Banknote } as const;

/** Take payment: any mix of cash (with change), card, mobile money and credit on the customer's account. */
export function PaymentDialog({ total, currency, branchId, customer, legs, setLegs, onClose, onComplete, busy, error, offline, savedAccounts, cannotSaveOffline }: {
  total: number; currency: string; branchId: string; customer: { id: string; name: string; phone: string };
  legs: PayLeg[]; setLegs: (change: (legs: PayLeg[]) => PayLeg[]) => void; onClose: () => void; onComplete: () => void; busy: boolean; error: Error | null;
  /** No connection: the sale is kept on this device and sent later. */
  offline: boolean; savedAccounts: { id: string; name: string }[];
  /** No connection and this browser cannot keep the sale on the device: it must not pretend. */
  cannotSaveOffline: boolean;
}) {
  const { t } = useTranslation("pos");
  const canCollect = useCan("payments.collect");
  const { enabledUnits } = useSession();
  const accounts = useQuery({
    enabled: !offline,
    queryKey: ["pos-terminal", "payment-accounts"],
    queryFn: () => unwrap(api.GET("/api/v1/payments/accounts")),
    staleTime: 5 * 60_000,
  });
  const mobileAccounts: PaymentAccount[] = accounts.data
    ? accounts.data.filter((a) => a.kind === "mobile_money" && a.is_active && (!a.branch_id || a.branch_id === branchId))
    : savedAccounts;

  const summary = paySummary(total, legs.filter((l) => Number(l.amount) > 0));
  const problem = payProblem(total, legs, !!customer.id);
  const creditAvailable = !!customer.id && enabledUnits.has("crm");
  const methods: PayMethod[] = ["cash", "card", "mobile_money", ...(creditAvailable ? ["credit" as const] : [])];

  const patch = (key: string, change: Partial<PayLeg>) => setLegs((all) => all.map((l) => (l.key === key ? { ...l, ...change } : l)));
  const add = (method: PayMethod) => setLegs((all) => [
    ...all,
    newLeg(method, paySummary(total, all.filter((l) => Number(l.amount) > 0)).remaining, {
      phone: method === "mobile_money" ? customer.phone : "", accountId: method === "mobile_money" ? (mobileAccounts[0]?.id ?? "") : "",
    }),
  ]);
  const balanceOf = (key: string) => {
    const others = legs.filter((l) => l.key !== key).reduce((s, l) => s + Number(l.amount || 0), 0);
    return text(Math.max(0, total - others));
  };
  const retryable = error instanceof ApiError ? error.status >= 500 : !!error;

  return (
    <Modal open onClose={busy ? () => undefined : onClose} title={t("terminal.pay.title")} size="md"
      footer={<>
        <Button variant="secondary" onClick={onClose} disabled={busy}>{t("terminal.pay.back")}</Button>
        <Button size="lg" loading={busy} disabled={problem !== null || cannotSaveOffline} onClick={onComplete}>
          {error ? t("terminal.retry") : offline ? t("terminal.sync.saveSale") : t("terminal.pay.complete")}
        </Button>
      </>}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (!problem && !busy) onComplete(); }}>
        <div className="grid grid-cols-3 gap-2 rounded-xl bg-sunken p-3 text-center">
          <Figure label={t("terminal.pay.due")} value={money(text(total), currency)} />
          <Figure label={t("terminal.pay.paid")} value={money(text(summary.paid), currency)} />
          {summary.paid >= total
            ? <Figure label={t("terminal.pay.change")} value={money(text(summary.change), currency)} tone="ok" />
            : <Figure label={t("terminal.pay.remaining")} value={money(text(summary.remaining), currency)} tone="bad" />}
        </div>

        <div className="flex flex-wrap gap-2">
          {methods.map((m) => {
            const Icon = METHOD_ICON[m];
            const blocked = offline && m === "credit";
            return <Button key={m} variant="secondary" size="lg" onClick={() => add(m)} disabled={blocked} className="flex-1"><Icon className="h-4 w-4" />{t(`terminal.pay.methods.${m}`)}</Button>;
          })}
        </div>
        {offline && (
          <div className="space-y-2">
            <Alert tone="warn">{cannotSaveOffline ? t("terminal.sync.noStorageSale") : t("terminal.sync.offlineSale")}</Alert>
            {creditAvailable && <p className="text-xs text-muted">{t("terminal.sync.creditOffline")}</p>}
          </div>
        )}

        <ul className="space-y-3">
          {legs.map((l) => {
            const Icon = METHOD_ICON[l.method];
            const locked = l.confirmed || !!l.intentId;
            return (
              <li key={l.key} className="space-y-2 rounded-xl border border-line p-3">
                <div className="flex items-end gap-2">
                  <span className="flex h-9 shrink-0 items-center gap-1.5 text-sm font-medium"><Icon className="h-4 w-4 text-muted" />{t(`terminal.pay.methods.${l.method}`)}</span>
                  <Field label={l.method === "cash" ? t("terminal.pay.handed") : t("terminal.pay.amount")} className="min-w-0 flex-1">
                    <NumberInput value={l.amount} onChange={(v) => patch(l.key, { amount: v })} disabled={locked} onFocus={(e) => e.target.select()} autoFocus={l === legs[legs.length - 1] && l.method !== "mobile_money"} />
                  </Field>
                  <Button variant="ghost" size="sm" disabled={locked} onClick={() => patch(l.key, { amount: balanceOf(l.key) })}>{t("terminal.pay.exact")}</Button>
                  {!l.confirmed && <IconButton label={t("terminal.pay.removeLeg")} onClick={() => setLegs((all) => all.filter((x) => x.key !== l.key))}><Trash2 className="h-4 w-4" /></IconButton>}
                </div>
                {l.method === "card" && (
                  <Field label={t("terminal.pay.slip")}><Input value={l.ref} onChange={(e) => patch(l.key, { ref: e.target.value })} maxLength={60} autoComplete="off" /></Field>
                )}
                {l.method === "mobile_money" && (
                  <MobileLeg leg={l} accounts={mobileAccounts} canPrompt={canCollect && !offline} offline={offline} onChange={(change) => patch(l.key, change)} />
                )}
                {l.method === "credit" && <p className="text-xs text-muted">{t("terminal.pay.creditHint", { name: customer.name })}</p>}
              </li>
            );
          })}
        </ul>

        {legs.length === 0 && <p className="text-center text-sm text-muted">{t("terminal.pay.pickMethod")}</p>}
        {problem && legs.length > 0 && <p className={cx("text-xs", problem === "short" ? "text-muted" : "text-warn")}>{t(`terminal.pay.problem.${problem}`)}</p>}
        {error && (
          <Alert tone="bad">
            <p className="font-medium">{error.message}</p>
            <p className="mt-1 text-xs">{retryable ? t("terminal.pay.retrySafe") : t("terminal.pay.fixAndRetry")}</p>
          </Alert>
        )}
        <button type="submit" className="hidden" />
      </form>
    </Modal>
  );
}

function Figure({ label, value, tone }: { label: string; value: string; tone?: "ok" | "bad" }) {
  return (
    <div>
      <p className="text-xs text-muted">{label}</p>
      <p className={cx("tnum text-lg font-bold", tone === "ok" && "text-ok", tone === "bad" && "text-bad")}>{value}</p>
    </div>
  );
}
