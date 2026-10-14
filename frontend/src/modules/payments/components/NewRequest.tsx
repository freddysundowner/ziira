import { useEffect, useState } from "react";

import {
  api, Alert, Button, Drawer, Field, Input, NumberInput, orNull, Select, toast, unwrap, useFormState, useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import { IntentStatus } from "./IntentStatus";
import { usePaymentAccounts } from "./usePaymentAccounts";

/**
 * Put a payment prompt on a customer's phone, then watch it. The Idempotency-Key is made once per time the form opens, so
 * a double click or a retry never prompts twice.
 */
export function NewRequest({ open, onClose, accountKind = "mobile_money" }: { open: boolean; onClose: () => void; accountKind?: string }) {
  const { t } = useTranslation("payments");
  const qc = useQueryClient();
  const accounts = usePaymentAccounts({ kind: accountKind, enabled: open });
  const f = useFormState({ payment_account_id: "", phone: "", amount: "", account_reference: "" });
  const [key, setKey] = useState(() => crypto.randomUUID());
  const [sent, setSent] = useState<{ id: string; companyId: string } | null>(null);
  const { reset } = f;
  useEffect(() => { if (open) { reset(); setSent(null); setKey(crypto.randomUUID()); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const list = accounts.data ?? [];
  const accountId = f.values.payment_account_id || list[0]?.id || "";

  const send = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/payments/intents", {
      params: { header: { "Idempotency-Key": key } },
      body: { payment_account_id: accountId, amount: f.values.amount, phone: f.values.phone.trim(), account_reference: orNull(f.values.account_reference) } })),
    onSuccess: (intent) => {
      void qc.invalidateQueries({ queryKey: ["payment-intents"] });
      setSent({ id: intent.id, companyId: list.find((a) => a.id === intent.payment_account_id)?.company_id ?? "" });
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });

  return (
    <Drawer open={open} onClose={onClose} title={t("newRequest")}
      footer={sent
        ? <Button onClick={onClose}>{t("close")}</Button>
        : <><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="request-form" loading={send.isPending} disabled={list.length === 0}>{t("sendRequest")}</Button></>}>
      {sent ? <IntentStatus intentId={sent.id} companyId={sent.companyId} /> : (
        <form id="request-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); send.mutate(); }}>
          <p className="text-sm text-muted">{t("requestHint")}</p>
          {accounts.isSuccess && list.length === 0 && <Alert tone="warn">{t("noCollectionAccount")}</Alert>}
          {list.length > 1 && (
            <Field label={t("collectInto")} error={f.error("payment_account_id")}>
              <Select value={accountId} onChange={(e) => f.set("payment_account_id", e.target.value)}>{list.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select>
            </Field>
          )}
          <Field label={t("phone")} required hint={t("phoneHint")} error={f.error("phone")}><Input type="tel" {...f.bind("phone")} required autoFocus /></Field>
          <Field label={t("amount")} required error={f.error("amount")}><NumberInput value={f.values.amount} onChange={(v) => f.set("amount", v)} required /></Field>
          <Field label={t("accountReference")} hint={t("accountReferenceHint")} error={f.error("account_reference")}><Input {...f.bind("account_reference")} maxLength={12} /></Field>
        </form>
      )}
    </Drawer>
  );
}
