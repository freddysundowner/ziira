import { useState } from "react";

import { Alert, api, Button, Field, FormGrid, Input, unwrap, useMutation, useTranslation } from "@/sdk";

/** Sends the business to the vendor's approval screen. They may type their own app's id and secret when the platform has none. */
export function OAuthButton({ connectionId, kind, title, authorised }: { connectionId: string; kind: string; title: string; authorised?: boolean }) {
  const { t } = useTranslation("connect");
  const [own, setOwn] = useState(false);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const start = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/connect/oauth/{kind}/start", {
      params: { path: { kind } },
      body: { connection_id: connectionId, client_id: clientId || null, client_secret: clientSecret || null },
    })),
    onSuccess: (r) => window.location.assign(r.authorization_url),
  });
  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">{t("oauth.explain", { title })}</p>
      {own && (
        <FormGrid>
          <Field label={t("oauth.clientId")}><Input value={clientId} onChange={(e) => setClientId(e.target.value)} autoComplete="off" /></Field>
          <Field label={t("oauth.clientSecret")} hint={t("oauth.clientHint")}><Input type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} autoComplete="off" /></Field>
        </FormGrid>
      )}
      {start.error && <Alert tone="bad">{start.error.message}{!own && <> <button type="button" className="underline" onClick={() => setOwn(true)}>{t("oauth.useOwn")}</button></>}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button loading={start.isPending} onClick={() => start.mutate()}>{authorised ? t("oauth.again", { title }) : t("oauth.button", { title })}</Button>
        {!own && <Button variant="ghost" onClick={() => setOwn(true)}>{t("oauth.useOwn")}</Button>}
      </div>
    </div>
  );
}
