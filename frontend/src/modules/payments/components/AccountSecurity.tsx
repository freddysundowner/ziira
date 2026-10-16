import { Copy } from "lucide-react";
import { useEffect, useState } from "react";

import { api, Alert, Button, ConfirmDialog, Drawer, Field, IconButton, Input, toast, unwrap, useMutation, useTranslation } from "@/sdk";

import type { PaymentAccount } from "../types";
import { ProviderFields } from "./ProviderFields";
import { fieldValues, missingRequired, usePaymentProviders } from "./usePaymentProviders";

/** The provider secrets of an account (stored encrypted, never shown again) and the callback addresses the provider calls. */
export function AccountSecurity({ account, onClose }: { account: PaymentAccount | null; onClose: () => void }) {
  const { t } = useTranslation("payments");
  const providers = usePaymentProviders(!!account);
  const provider = providers.data?.providers.find((p) => p.name === account?.provider);
  const fields = provider?.credential_fields ?? [];
  const [values, setValues] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [urls, setUrls] = useState<Record<string, string> | null>(null);
  const id = account?.id ?? "";
  useEffect(() => { setValues({}); setProblem(null); setUrls(null); }, [id]);

  const saveCredentials = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PUT("/api/v1/payments/accounts/{account_id}/credentials", { params: { path: { account_id: id } }, body: fieldValues(fields, values) })),
    onSuccess: () => { toast(t("credentialsSaved"), "ok"); setValues({}); setProblem(null); },
    onError: (e) => { setProblem((e as Error).message); toast((e as Error).message, "bad"); },
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
        <form className="space-y-4" onSubmit={(e) => {
          e.preventDefault();
          const missing = missingRequired(fields, values);
          if (missing) { setProblem(t("fieldRequired", { name: missing.label })); return; }
          saveCredentials.mutate();
        }}>
          <div><h3 className="text-sm font-semibold">{t("credentials")}</h3><p className="text-xs text-muted">{t("credentialsHint")}</p></div>
          {providers.isLoading && <p className="text-sm text-muted">{t("loadingProvider")}</p>}
          {!providers.isLoading && !provider && <Alert tone="warn">{t("providerNotOn", { name: account.provider })}</Alert>}
          {provider && fields.length === 0 && <p className="text-sm text-muted">{t("noCredentials")}</p>}
          <ProviderFields fields={fields} values={values} onChange={(k, v) => setValues((x) => ({ ...x, [k]: v }))} />
          {problem && <Alert tone="bad">{problem}</Alert>}
          {fields.length > 0 && <Button type="submit" loading={saveCredentials.isPending}>{t("saveCredentials")}</Button>}
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
