import { CheckCircle2, Smartphone } from "lucide-react";
import { useEffect } from "react";

import { api, Alert, Button, Field, Input, Select, Spinner, unwrap, useMutation, useQuery, useTranslation, type Schemas } from "@/sdk";

import type { PayLeg } from "../cart";

export type PaymentAccount = Schemas["ziira__modules__payments__api__schemas__AccountOut"];

const FINAL = ["succeeded", "failed", "cancelled", "timeout"];

/**
 * The mobile money part of a payment: send a prompt to the customer's phone and wait for them to approve it, or type the
 * code from the customer's confirmation message. The prompt carries an Idempotency-Key, so a retry never prompts twice.
 */
export function MobileLeg({ leg, accounts, canPrompt, onChange }: {
  leg: PayLeg; accounts: PaymentAccount[]; canPrompt: boolean; onChange: (patch: Partial<PayLeg>) => void;
}) {
  const { t } = useTranslation("pos");
  const accountId = leg.accountId || accounts[0]?.id || "";

  const send = useMutation({
    meta: { silent: true },
    mutationFn: (key: string) => unwrap(api.POST("/api/v1/payments/intents", {
      params: { header: { "Idempotency-Key": key } },
      body: { payment_account_id: accountId, amount: leg.amount, phone: leg.phone.trim() },
    })),
    onSuccess: (intent) => onChange({ intentId: intent.id }),
  });

  const intent = useQuery({
    enabled: !!leg.intentId && !leg.confirmed,
    queryKey: ["pos-terminal", "intent", leg.intentId],
    queryFn: () => unwrap(api.GET("/api/v1/payments/intents/{intent_id}", { params: { path: { intent_id: leg.intentId } } })),
    refetchInterval: (query) => (FINAL.includes(query.state.data?.status ?? "") ? false : 3000),
    retry: true,
  });
  const status = intent.data?.status;

  useEffect(() => {
    if (status === "succeeded") onChange({ confirmed: true, ref: intent.data?.receipt ?? leg.ref });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- react once to the prompt's final status
  }, [status]);

  const waiting = !!leg.intentId && !leg.confirmed && !(status && FINAL.includes(status));
  const failed = !!status && status !== "succeeded" && FINAL.includes(status);
  const restart = () => onChange({ intentId: "", intentKey: "" });
  const sendPrompt = () => {
    const key = leg.intentKey || crypto.randomUUID();
    if (!leg.intentKey) onChange({ intentKey: key });
    send.mutate(key);
  };

  if (leg.confirmed) {
    return <p className="flex items-center gap-1.5 text-sm text-ok"><CheckCircle2 className="h-4 w-4" />{t("terminal.pay.mobile.confirmed", { code: leg.ref || "—" })}</p>;
  }

  return (
    <div className="space-y-2">
      {canPrompt && accounts.length > 1 && !leg.intentId && (
        <Field label={t("terminal.pay.mobile.account")}>
          <Select value={accountId} onChange={(e) => onChange({ accountId: e.target.value })}>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </Select>
        </Field>
      )}
      {canPrompt && accountId && !waiting && (
        <div className="flex items-end gap-2">
          <Field label={t("terminal.pay.mobile.phone")} className="min-w-0 flex-1">
            <Input inputMode="tel" value={leg.phone} onChange={(e) => onChange({ phone: e.target.value })} placeholder={t("terminal.pay.mobile.phoneHint")} />
          </Field>
          <Button variant="secondary" loading={send.isPending} disabled={!leg.phone.trim() || Number(leg.amount) <= 0} onClick={sendPrompt}>
            <Smartphone className="h-4 w-4" />{send.error ? t("terminal.retry") : t("terminal.pay.mobile.send")}
          </Button>
        </div>
      )}
      {send.error && <Alert tone="bad">{send.error.message} {t("terminal.pay.mobile.sendSafe")}</Alert>}
      {waiting && (
        <Alert tone="info">
          <span className="flex flex-wrap items-center justify-between gap-2">
            <span className="flex items-center gap-2"><Spinner />{intent.error ? t("terminal.pay.mobile.pollError") : t("terminal.pay.mobile.waiting")}</span>
            <Button size="sm" variant="ghost" onClick={restart}>{t("terminal.pay.mobile.stop")}</Button>
          </span>
        </Alert>
      )}
      {failed && (
        <Alert tone="bad">
          <span className="flex flex-wrap items-center justify-between gap-2">
            <span>{t(`terminal.pay.mobile.status.${status}`, t("terminal.pay.mobile.status.failed"))}</span>
            <Button size="sm" variant="secondary" onClick={restart}>{t("terminal.pay.mobile.again")}</Button>
          </span>
        </Alert>
      )}
      {!waiting && (
        <Field label={t("terminal.pay.mobile.code")} hint={canPrompt ? t("terminal.pay.mobile.codeHint") : undefined}>
          <Input value={leg.ref} onChange={(e) => onChange({ ref: e.target.value.toUpperCase() })} autoComplete="off" maxLength={60} />
        </Field>
      )}
    </div>
  );
}
