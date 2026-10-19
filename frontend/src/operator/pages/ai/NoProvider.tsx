import type { ReactNode } from "react";

import { Alert, Button, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import type { AiOverview } from "../../helpers/ai";
import { useOperatorCan } from "../../me";
import { useChange } from "../../stepUp";

/** "None: AI off" picked in the dropdown: nothing to fill in, only the button that switches the platform's choice off. */
export function NoProvider({ overview, onChanged, providerField, status }: { overview: AiOverview; onChanged: () => void; providerField: ReactNode; status: ReactNode }) {
  const { t } = useTranslation("operator");
  const editable = useOperatorCan("platform.ai");
  const off = useChange(() => opUnwrap(opApi.PUT("/api/v1/operator/ai/active", { body: { provider: null } })), {
    onSuccess: () => { toast(t("ai.form.nowOff"), "ok"); onChanged(); },
  });
  const already = overview.default_provider === null;
  return (
    <div className="space-y-3">
      <div className="grid gap-4 min-[900px]:grid-cols-2"><div className="min-w-0">{providerField}</div><div className="min-w-0 self-start">{status}</div></div>
      <Alert tone="info">{t("ai.form.offNote")}</Alert>
      {off.isError && <Alert tone="bad">{off.error.message}</Alert>}
      {editable && <div className="flex justify-end"><Button loading={off.isPending} disabled={already} onClick={() => off.mutate(undefined)}>{t("ai.form.switchOff")}</Button></div>}
    </div>
  );
}
