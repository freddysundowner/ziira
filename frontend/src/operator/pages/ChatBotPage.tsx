import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { Alert, Badge, Card, ErrorState, PageHeader, Skeleton, Switch, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../client";
import { useOperatorCan } from "../me";
import { useChange } from "../stepUp";
import { ConnectCard } from "./chat/ConnectCard";
import { DevCard } from "./chat/DevCard";
import { KeyCard } from "./chat/KeyCard";
import { notReadyKey, steps } from "./chat/logic";
import { SayCard } from "./chat/SayCard";
import { TryCard } from "./chat/TryCard";
import { WaitingCard } from "./chat/WaitingCard";
import { WebhookCard } from "./chat/WebhookCard";

const KEY = ["operator", "chat"];

/** Platform > WhatsApp bot: connect a number through the chat provider and let the website assistant's checked answers reach it. */
export default function ChatBotPage() {
  const { t } = useTranslation("operator");
  const editable = useOperatorCan("platform.settings");
  const queryClient = useQueryClient();
  const page = useQuery({ queryKey: KEY, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/chat")) });
  const refresh = useCallback(() => void queryClient.invalidateQueries({ queryKey: KEY }), [queryClient]);
  const toggle = useChange((enabled: boolean) => opUnwrap(opApi.PUT("/api/v1/operator/chat/enabled", { body: { enabled } })), {
    onSuccess: (r) => { toast(t(r.enabled ? "chat.bot.nowOn" : "chat.bot.nowOff"), "ok"); refresh(); },
  });

  if (page.isPending) return <Skeleton className="h-64 w-full" />;
  if (page.isError) return <ErrorState title={t("chat.loadFailed")} message={page.error.message} onRetry={() => void page.refetch()} />;
  const o = page.data;
  const progress = steps(o);
  const why = notReadyKey(o);
  return (
    <div className="space-y-5">
      <PageHeader title={t("chat.title")} description={t("chat.intro")} />
      {!editable && <Alert tone="info">{t("chat.readOnly")}</Alert>}
      {o.fake && <Alert tone="warn">{t("chat.practice")}</Alert>}

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <ol className="flex flex-wrap gap-2" aria-label={t("chat.steps.title")}>
            {progress.map((s) => <li key={s.id}><Badge tone={s.done ? "ok" : s.current ? "warn" : "neutral"}>{t(`chat.steps.${s.id}`)}</Badge></li>)}
          </ol>
          <label className="flex items-center gap-2 text-sm font-medium">
            <Switch checked={o.bot.enabled} label={t("chat.bot.switch")} disabled={!editable || toggle.isPending || (!o.bot.enabled && !o.bot.can_enable)} onChange={(v) => toggle.mutate(v)} />
            <span>{t("chat.bot.switch")}</span>
            <Badge tone={o.bot.enabled ? "ok" : "neutral"}>{o.bot.enabled ? t("chat.bot.on") : t("chat.bot.off")}</Badge>
          </label>
        </div>
        {why && !o.bot.enabled && <p className="mt-2 text-sm text-muted" data-testid="not-ready">{t(`chat.bot.notReady.${why}`)}</p>}
      </Card>

      <KeyCard overview={o} editable={editable} onChanged={refresh} />
      <ConnectCard overview={o} editable={editable} onChanged={refresh} />
      <WebhookCard overview={o} editable={editable} onChanged={refresh} />
      <SayCard key={JSON.stringify(o.bot.texts)} overview={o} editable={editable} onChanged={refresh} />
      <TryCard overview={o} editable={editable} />
      {o.fake && editable && <DevCard connected={o.connection.state === "connected"} onChanged={refresh} />}
      <WaitingCard overview={o} editable={editable} onChanged={refresh} />
    </div>
  );
}
