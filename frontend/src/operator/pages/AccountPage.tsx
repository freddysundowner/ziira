import { useQueryClient } from "@tanstack/react-query";

import { Button, Card, PageHeader, toast, useTranslation } from "@/sdk";

import { opApi } from "../client";
import { PasswordForm } from "../components/PasswordForm";
import { useOperatorMe } from "../me";
import { useOperator } from "../session";

/** The operator's own account: change the password, and end every sign-in on every device. */
export default function AccountPage() {
  const { t } = useTranslation("operator");
  const me = useOperatorMe();
  const { signOut } = useOperator();
  const queryClient = useQueryClient();

  async function signOutEverywhere() {
    try {
      await opApi.POST("/api/v1/operator/sign-out-all");
    } finally {
      await signOut();
    }
  }

  return (
    <>
      <PageHeader title={t("account.title")} description={me.data ? `${me.data.name} · ${me.data.email}` : undefined} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title={t("account.passwordTitle")} description={t("account.passwordHint")}>
          <PasswordForm onDone={() => { toast(t("account.changed"), "ok"); void queryClient.invalidateQueries({ queryKey: ["operator", "me"] }); }} />
        </Card>
        <Card title={t("account.signOutAllTitle")} description={t("account.signOutAllHint")}>
          <Button variant="secondary" onClick={() => void signOutEverywhere()}>{t("account.signOutAll")}</Button>
        </Card>
      </div>
    </>
  );
}
