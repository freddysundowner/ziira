import { Link } from "react-router-dom";

import { api, Badge, type BadgeTone, Card, ErrorState, formatDate, SkeletonRows, unwrap, useCan, useQuery, useTranslation } from "@/sdk";

const TONE: Record<string, BadgeTone> = { sent: "ok", queued: "info", failed: "bad", skipped: "neutral" };

/** The last few messages, so a new setup can be checked at a glance. The full log is under Notifications. */
export default function RecentMessages({ companyId }: { companyId: string }) {
  const { t } = useTranslation("messaging");
  const canLog = useCan("settings.manage");
  const recent = useQuery({
    queryKey: ["recent-messages", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/notifications", { params: { query: { company_id: companyId, limit: 8 } } })),
  });
  return (
    <Card title={t("recent")} actions={canLog ? <Link className="text-xs font-medium text-brand-strong hover:underline" to="/admin/notifications">{t("fullLog")}</Link> : undefined} flush>
      {recent.error ? <ErrorState message={recent.error.message} onRetry={() => void recent.refetch()} /> : !recent.data ? <SkeletonRows rows={3} cols={3} /> : recent.data.length === 0 ? (
        <p className="p-4 text-sm text-muted">{t("noRecent")}</p>
      ) : (
        <ul className="divide-y divide-line">
          {recent.data.map((n) => (
            <li key={n.id} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm">
              <div className="min-w-0">
                <p className="truncate"><span className="tnum">{n.recipient}</span> <span className="text-muted">· {t(n.channel === "sms" ? "sms" : "email")}</span></p>
                <p className="text-xs text-muted">{formatDate(n.created_at, true)}{n.error ? ` · ${n.error}` : ""}</p>
              </div>
              <Badge tone={TONE[n.status] ?? "neutral"}>{t(`status.${n.status}`, { defaultValue: n.status })}</Badge>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
