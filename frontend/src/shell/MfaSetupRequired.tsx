import { Alert, Button, TwoStepSetup, useSession, useTranslation } from "@/sdk";

import { AuthShell } from "./AuthShell";

/** Shown instead of the app when the business requires two-step verification of this person and it is not set up yet. */
export function MfaSetupRequired() {
  const { t } = useTranslation();
  const { retry, signOut } = useSession();
  return (
    <AuthShell>
      <div className="space-y-5">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold">{t("mfa.setupRequiredTitle")}</h1>
          <p className="text-sm text-muted">{t("mfa.setupRequiredHint")}</p>
        </div>
        <Alert tone="info">{t("mfa.setupRequiredWhy")}</Alert>
        {/* Reloading the session fetches fresh tokens, which no longer carry the "setup first" limit. */}
        <TwoStepSetup onFinished={retry} />
        <Button variant="ghost" className="w-full" onClick={() => void signOut()}>{t("signOut")}</Button>
      </div>
    </AuthShell>
  );
}
