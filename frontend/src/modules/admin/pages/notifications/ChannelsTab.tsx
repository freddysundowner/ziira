import { Mail, MessageSquare } from "lucide-react";

import { api, Badge, Card, EmptyState, ErrorState, SkeletonRows, unwrap, useChannels, useQuery, useTranslation } from "@/sdk";

/** Read-only state of the channels (never their keys). Setting them up is the messaging plugin's screen. */
export default function ChannelsTab({ companyId }: { companyId: string | undefined }) {
  const { t } = useTranslation("kernel");
  const channels = useQuery({
    enabled: !!companyId, queryKey: ["notification-channels", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/notifications/channels", { params: { query: { company_id: companyId! } } })),
  });
  const available = useChannels(companyId);
  if (!companyId) return null;
  if (channels.error) return <ErrorState message={channels.error.message} onRetry={() => void channels.refetch()} />;
  if (available.error) return <ErrorState message={available.error.message} onRetry={() => void available.refetch()} />;
  if (!channels.data || !available.data) return <SkeletonRows rows={2} cols={3} />;
  if (available.data.length === 0) return <EmptyState title={t("noChannels")} hint={t("noChannelsHint")} />;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      {available.data.map((info) => {
        const c = info.channel;
        const active = channels.data.find((x) => x.channel === c && x.status === "active");
        return (
          <Card key={c} title={<span className="inline-flex items-center gap-2">{c === "email" ? <Mail className="h-4 w-4" /> : <MessageSquare className="h-4 w-4" />}{info.label}</span>}
            actions={<Badge tone={active ? "ok" : "neutral"}>{active ? t("configured") : t("notConfigured")}</Badge>}>
            {active ? <p className="text-sm text-muted">{t("viaProvider", { provider: active.provider ?? "—", label: active.label })}</p> : <EmptyState title={t("channelOff")} hint={t("channelOffHint")} />}
          </Card>
        );
      })}
    </div>
  );
}
