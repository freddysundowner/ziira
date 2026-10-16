import { Mail } from "lucide-react";
import { Link } from "react-router-dom";

import { Alert, Button, useTranslation } from "@/sdk";

/** After the request is sent: look in your inbox. Outside production the API also hands back the link (no mailbox is read there). */
export function CheckEmail({ email, devToken, onChange }: { email: string; devToken: string | null; onChange: () => void }) {
  const { t } = useTranslation();
  return (
    <div className="mx-auto max-w-xl space-y-5 py-8 text-center sm:py-16">
      <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-brand-soft text-brand-strong"><Mail className="h-8 w-8" aria-hidden /></span>
      <h1 tabIndex={-1} data-step-heading className="text-3xl font-semibold">{t("signup.sent.title")}</h1>
      <p className="text-base text-muted">{t("signup.sent.body", { email })}</p>
      {devToken && (
        <Alert tone="warn" className="text-left">
          {t("register.devOnly")} <Link className="font-medium underline" to={`/register/verify?token=${encodeURIComponent(devToken)}`}>{t("register.devLink")}</Link>
        </Alert>
      )}
      <p className="text-sm text-muted">{t("signup.sent.wrong")}</p>
      <div className="flex flex-wrap items-center justify-center gap-3">
        <Button variant="secondary" onClick={onChange}>{t("signup.sent.fix")}</Button>
        <Link className="text-sm font-medium text-brand-strong hover:underline" to="/">{t("register.backToSignIn")}</Link>
      </div>
    </div>
  );
}
