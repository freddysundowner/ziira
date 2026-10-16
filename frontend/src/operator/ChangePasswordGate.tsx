import { useQueryClient } from "@tanstack/react-query";

import { Alert, Button, toast, useTranslation } from "@/sdk";

import { PasswordForm } from "./components/PasswordForm";
import { useOperator } from "./session";

/**
 * Shown instead of the console after signing in with a temporary password. Nothing else is open until a new password
 * is chosen (the server refuses every other call too); signing out is the only way to leave.
 */
export function ChangePasswordGate() {
  const { t } = useTranslation("operator");
  const { signOut } = useOperator();
  const queryClient = useQueryClient();
  return (
    <div className="flex min-h-screen items-center justify-center bg-bg p-5">
      <main className="w-full max-w-sm space-y-6">
        <div className="space-y-4 rounded-2xl border border-line bg-surface p-6 shadow-card">
          <h1 className="text-xl font-semibold">{t("account.forcedTitle")}</h1>
          <Alert tone="info">{t("account.forcedHint")}</Alert>
          <PasswordForm onDone={() => { toast(t("account.changed"), "ok"); void queryClient.invalidateQueries({ queryKey: ["operator", "me"] }); }}>
            <Button type="button" variant="ghost" onClick={() => void signOut()}>{t("signOut")}</Button>
          </PasswordForm>
        </div>
      </main>
    </div>
  );
}
