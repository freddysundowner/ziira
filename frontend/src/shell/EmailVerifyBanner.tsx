import { MailCheck } from "lucide-react";
import { useState } from "react";

import { api, Button, toast, unwrap, useQuery, useTranslation } from "@/sdk";

/** Above every page for a new owner who has not confirmed their email address yet: they are already in, this only asks. */
export function EmailVerifyBanner() {
  const { t } = useTranslation();
  const me = useQuery({ queryKey: ["support-banner"], queryFn: () => unwrap(api.GET("/api/v1/auth/me")), refetchInterval: 60_000 });
  const [busy, setBusy] = useState(false);
  if (!me.data || me.data.email_verified !== false) return null;

  async function resend() {
    setBusy(true);
    try {
      const { data, response } = await api.POST("/api/v1/auth/email-confirmation/resend");
      if (response.status === 429) toast(t("emailBanner.wait"), "warn");
      else if (response.ok && (data as { sent?: boolean } | undefined)?.sent) toast(t("emailBanner.sent"), "ok");
      else if (response.ok) void me.refetch();
      else toast(t("emailBanner.failed"), "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="status" className="no-print flex flex-wrap items-center justify-center gap-x-3 gap-y-1 bg-warn-soft px-3 py-2 text-center text-sm text-warn">
      <MailCheck className="h-4 w-4 shrink-0" aria-hidden />
      <span className="font-medium">{t("emailBanner.text", { email: me.data.email ?? "" })}</span>
      <Button size="sm" variant="secondary" loading={busy} onClick={() => void resend()}>{t("emailBanner.resend")}</Button>
    </div>
  );
}
