import { useEffect, useState } from "react";

import { Alert, Button, Modal, type Schemas, Spinner, useTranslation } from "@/sdk";

import { CopyButton } from "./bits";

/** Draws the QR code in the browser: the secret never goes to any other service. */
function Qr({ value, alt }: { value: string; alt: string }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void import("qrcode")
      .then(({ toDataURL }) => toDataURL(value, { margin: 1, width: 180, errorCorrectionLevel: "M" }))
      .then((url) => { if (live) setSrc(url); })
      .catch(() => undefined);
    return () => { live = false; };
  }, [value]);
  return (
    <div className="mx-auto flex h-[196px] w-[196px] items-center justify-center rounded-xl bg-white p-2">
      {src ? <img src={src} alt={alt} width={180} height={180} /> : <Spinner />}
    </div>
  );
}

/**
 * A new operator's (or a reset) second-factor secret. It is shown once, here: it is given to that person, who adds it to
 * their authenticator app. Nothing here is kept after the box is closed.
 */
export function SecretDialog({ secret, onClose }: { secret: Schemas["OperatorSecretOut"]; onClose: () => void }) {
  const { t } = useTranslation("operator");
  return (
    <Modal open onClose={onClose} title={t("operators.secretTitle")} size="md" footer={<Button onClick={onClose}>{t("operators.secretSaved")}</Button>}>
      <div className="space-y-4 text-sm">
        <Alert tone="warn">{t("operators.secretWarning")}</Alert>
        <Qr value={secret.otpauth_uri} alt={t("operators.qrAlt")} />
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">{t("operators.secretKey")}</p>
          <p className="break-all rounded-lg bg-sunken px-3 py-2 font-mono text-sm" data-testid="mfa-secret">{secret.mfa_secret}</p>
          <div className="mt-2"><CopyButton text={secret.mfa_secret} label={t("operators.copySecret")} /></div>
        </div>
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">{t("operators.secretLink")}</p>
          <p className="break-all rounded-lg bg-sunken px-3 py-2 font-mono text-xs">{secret.otpauth_uri}</p>
          <div className="mt-2"><CopyButton text={secret.otpauth_uri} label={t("operators.copyLink")} /></div>
        </div>
      </div>
    </Modal>
  );
}
