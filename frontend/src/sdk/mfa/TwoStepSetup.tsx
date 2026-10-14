import { Copy } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, unwrap } from "../api";
import { useTranslation } from "../i18n";
import { toast } from "../notify";
import { Alert, Button, ErrorState, Field, Input, Spinner } from "../ui";
import { useMutation } from "@tanstack/react-query";
import { BackupCodes } from "./BackupCodes";
import { copyText } from "./clipboard";
import { cleanAuthenticatorCode, groupSecret, isAuthenticatorCode } from "./helpers";

/** Draws the QR code in the browser: the secret never goes to any other service. */
function QrCode({ value, alt }: { value: string; alt: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void import("qrcode").then(({ toDataURL }) => toDataURL(value, { margin: 1, width: 200, errorCorrectionLevel: "M" })).then((url) => { if (live) setSrc(url); });
    return () => { live = false; };
  }, [value]);
  return (
    <div className="mx-auto flex h-[216px] w-[216px] items-center justify-center rounded-xl bg-white p-2">
      {src ? <img src={src} alt={alt} width={200} height={200} /> : <Spinner />}
    </div>
  );
}

/**
 * Setting up two-step verification: shows the secret and QR code, asks for the first code, then shows the backup codes once.
 * `onFinished` runs only after the person confirmed they saved the backup codes.
 */
export function TwoStepSetup({ onFinished, onCancel }: { onFinished: () => void; onCancel?: () => void }) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const started = useRef(false);

  const setup = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/auth/mfa/setup")),
  });
  const enable = useMutation({
    meta: { silent: true },
    mutationFn: (value: string) => unwrap(api.POST("/api/v1/auth/mfa/enable", { body: { code: value } })),
    onSuccess: (data) => setCodes(data.backup_codes),
    onError: () => setCode(""),
  });

  useEffect(() => {
    if (started.current) return;            // asking again would replace the secret the person is about to scan
    started.current = true;
    setup.mutate();
  }, [setup]);

  if (codes) return <BackupCodes codes={codes} onDone={onFinished} />;
  if (setup.isError) return <ErrorState title={t("mfa.setupFailed")} message={setup.error.message} onRetry={() => setup.mutate()} />;
  if (!setup.data) return <p className="flex items-center justify-center gap-2 p-8 text-sm text-muted"><Spinner /> {t("loading")}</p>;

  const { secret, otpauth_uri } = setup.data;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (isAuthenticatorCode(code) && !enable.isPending) enable.mutate(code);
  };
  const copySecret = async () => toast(t((await copyText(secret)) ? "mfa.copied" : "mfa.copyFailed"), "ok");

  return (
    <div className="space-y-5">
      <section className="space-y-3">
        <h3 className="text-sm font-semibold">{t("mfa.step1")}</h3>
        <p className="text-sm text-muted">{t("mfa.scanHint")}</p>
        <QrCode value={otpauth_uri} alt={t("mfa.qrAlt")} />
        <div className="space-y-1.5">
          <p className="text-xs text-muted">{t("mfa.orType")}</p>
          <div className="flex items-center gap-2 rounded-lg border border-line bg-sunken px-3 py-2">
            <code className="flex-1 select-all break-all font-mono text-sm tracking-wider">{groupSecret(secret)}</code>
            <Button size="sm" variant="ghost" onClick={() => void copySecret()}><Copy className="h-4 w-4" />{t("mfa.copy")}</Button>
          </div>
        </div>
      </section>
      <form onSubmit={submit} className="space-y-3">
        <h3 className="text-sm font-semibold">{t("mfa.step2")}</h3>
        <Field label={t("mfa.codeLabel")}>
          <Input value={code} onChange={(e) => setCode(cleanAuthenticatorCode(e.target.value))} inputMode="numeric" autoComplete="one-time-code" placeholder="123456"
            className="text-center font-mono text-lg tracking-[0.4em]" autoFocus />
        </Field>
        {enable.isError && <Alert tone="bad">{enable.error.message}</Alert>}
        <div className="flex gap-2">
          {onCancel && <Button variant="secondary" size="lg" onClick={onCancel}>{t("mfa.cancel")}</Button>}
          <Button type="submit" size="lg" className="flex-1" loading={enable.isPending} disabled={!isAuthenticatorCode(code)}>{t("mfa.enable")}</Button>
        </div>
      </form>
    </div>
  );
}
