import { Link } from "react-router-dom";

import { useTranslation } from "@/sdk";

/** Shown instead of the wizard when the platform has closed sign-up, or opened it by invitation only and this visit has no invitation. */
export function SignUpClosed({ invite, support }: { invite: boolean; support: string }) {
  const { t } = useTranslation();
  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-md space-y-4 rounded-2xl border border-line bg-surface p-8 text-center">
        <h1 className="text-2xl font-semibold">{invite ? t("signup.inviteTitle") : t("signup.closedTitle")}</h1>
        <p className="text-muted">{invite ? t("signup.inviteBody") : t("signup.closedBody")}</p>
        {support && <a className="block font-medium text-brand-strong hover:underline" href={`mailto:${support}`}>{t("signup.contact", { email: support })}</a>}
        <Link to="/" className="block text-sm font-medium text-brand-strong hover:underline">{t("signup.haveAccount")}</Link>
      </div>
    </div>
  );
}
