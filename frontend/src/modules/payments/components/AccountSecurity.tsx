import { Copy } from "lucide-react";
import { useEffect, useState } from "react";

import { api, Alert, Button, ConfirmDialog, Drawer, Field, IconButton, Input, toast, unwrap, useFormState, useMutation, useTranslation } from "@/sdk";

import type { PaymentAccount } from "../types";

/** The provider secrets of an account (stored encrypted, never shown again) and the callback addresses the provider calls. */
export function AccountSecurity({ account, onClose }: { account: PaymentAccount | null; onClose: () => void }) {
  const { t } = useTranslation("payments");
  const f = useFormState({ consumer_key: "", consumer_secret: "", passkey: "" });
  const [confirming, setConfirming] = useState(false);
  const [urls, setUrls] = useState<Record<string, string> | null>(null);
  const id = account?.id ?? "";
  const { reset } = f;
  useEffect(() => { reset(); setUrls(null); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveCredentials = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PUT("/api/v1/payments/accounts/{account_id}/credentials", { params: { path: { account_id: id } }, body: {
      consumer_key: f.values.consumer_key.trim(), consumer_secret: f.values.consumer_secret.trim(), passkey: f.values.passkey.trim() } })),
    onSuccess: () => { toast(t("credentialsSaved"), "ok"); f.reset(); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const rotate = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/payments/accounts/{account_id}/callback-token", { params: { path: { account_id: id } } })),
    onSuccess: (r) => { setUrls(r.urls); setConfirming(false); toast(t("tokenMade"), "ok"); },
  });

  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); toast(t("copied"), "ok"); } catch { toast(t("copyFailed"), "warn"); }
  }

  if (!account) return null;
  return (
    <Drawer open onClose={onClose} title={t("connection", { name: account.name })}>
      <div className="space-y-8">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); saveCredentials.mutate(); }}>
          <div><h3 className="text-sm font-semibold">{t("credentials")}</h3><p className="text-xs text-muted">{t("credentialsHint")}</p></div>
          <Field label={t("consumerKey")} required error={f.error("consumer_key")}><Input {...f.bind("consumer_key")} required autoComplete="off" /></Field>
          <Field label={t("consumerSecret")} required error={f.error("consumer_secret")}><Input type="password" {...f.bind("consumer_secret")} required autoComplete="new-password" /></Field>
          <Field label={t("passkey")} required error={f.error("passkey")}><Input type="password" {...f.bind("passkey")} required autoComplete="new-password" /></Field>
          <Button type="submit" loading={saveCredentials.isPending}>{t("saveCredentials")}</Button>
        </form>
        <div className="space-y-3">
          <div><h3 className="text-sm font-semibold">{t("callbackAddresses")}</h3><p className="text-xs text-muted">{t("callbackHint")}</p></div>
          {urls ? (
            <>
              <Alert tone="warn">{t("callbackShownOnce")}</Alert>
              {Object.entries(urls).map(([name, url]) => (
                <Field key={name} label={name.replace(/_/g, " ")}>
                  <div className="flex items-center gap-1"><Input readOnly value={url} onFocus={(e) => e.currentTarget.select()} className="font-mono text-xs" /><IconButton label={t("copy")} onClick={() => void copy(url)}><Copy className="h-4 w-4" /></IconButton></div>
                </Field>
              ))}
            </>
          ) : <Button variant="secondary" onClick={() => setConfirming(true)}>{t("makeCallbackToken")}</Button>}
        </div>
      </div>
      <ConfirmDialog open={confirming} onClose={() => setConfirming(false)} onConfirm={() => rotate.mutate()} busy={rotate.isPending} danger
        title={t("makeCallbackToken")} confirmLabel={t("makeCallbackToken")} message={t("rotateAsk")} />
    </Drawer>
  );
}
