import { useState } from "react";

import { Alert, Badge, Button, Card, ConfirmDialog, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";
import { addressProblem, type ChatOverview } from "./logic";

/** The address the provider calls (its token hidden) and the signing secret, which is handled entirely by the server. */
export function WebhookCard({ overview: o, editable, onChanged }: { overview: ChatOverview; editable: boolean; onChanged: () => void }) {
  const { t } = useTranslation("operator");
  const [confirm, setConfirm] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const rotate = useChange(() => opUnwrap(opApi.POST("/api/v1/operator/chat/rotate-secret")), {
    onSuccess: () => { setConfirm(false); toast(t("chat.webhook.rotated"), "ok"); onChanged(); },
    onError: (e) => { setConfirm(false); setProblem(e.message); },
  });
  const warn = addressProblem(o);
  return (
    <Card title={t("chat.webhook.title")} description={t("chat.webhook.intro")}
      actions={<Badge tone={o.webhook.secret_set ? "ok" : "neutral"}>{o.webhook.secret_set ? t("chat.webhook.secretSet") : t("chat.webhook.secretNotSet")}</Badge>}>
      <div className="space-y-3">
        <div>
          <p className="text-xs text-muted">{t("chat.webhook.address")}</p>
          <code className="block break-all rounded bg-sunken px-2 py-1 text-sm" data-testid="webhook-url">{o.webhook.url ?? t("chat.webhook.noAddress")}</code>
          <p className="mt-1 text-xs text-muted">{t("chat.webhook.hidden")}</p>
        </div>
        {warn && <Alert tone="warn">{t(`chat.webhook.problems.${warn}`)}</Alert>}
        {problem && <Alert tone="bad">{problem}</Alert>}
        {editable && (
          <div className="flex justify-end">
            <Button variant="secondary" size="sm" disabled={o.connection.state !== "connected"} onClick={() => { setProblem(null); setConfirm(true); }}>{t("chat.webhook.rotate")}</Button>
          </div>
        )}
      </div>
      <ConfirmDialog open={confirm} title={t("chat.webhook.rotateTitle")} message={t("chat.webhook.rotateText")} confirmLabel={t("chat.webhook.rotate")}
        busy={rotate.isPending} onConfirm={() => rotate.mutate(undefined)} onClose={() => setConfirm(false)} />
    </Card>
  );
}
