import { useQuery } from "@tanstack/react-query";

import { Badge, Card, EmptyState, ErrorState, formatDate, Skeleton, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";

/** The last 50 messages the platform sent: kind, masked recipient, result. Never the message itself. */
export function MailLog({ version }: { version: unknown }) {
  const { t } = useTranslation("operator");
  const log = useQuery({ queryKey: ["operator", "email-log", version], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/email/log", { params: { query: { limit: 50 } } })) });
  return (
    <Card title={t("email.log.title")} description={t("email.log.retention")}>
      {log.isPending ? <Skeleton className="h-24 w-full" /> : log.isError ? <ErrorState title={t("email.loadFailed")} message={log.error.message} onRetry={() => void log.refetch()} />
        : log.data.length === 0 ? <EmptyState title={t("email.log.empty")} /> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-muted"><th className="py-1 pr-3">{t("email.log.time")}</th><th className="pr-3">{t("email.log.kind")}</th><th className="pr-3">{t("email.log.to")}</th><th>{t("email.log.status")}</th></tr></thead>
              <tbody>
                {log.data.map((l) => (
                  <tr key={l.id} className="border-t border-line align-top">
                    <td className="py-1.5 pr-3 whitespace-nowrap">{formatDate(l.sent_at, true)}</td>
                    <td className="pr-3">{t(`email.log.kinds.${l.kind}`, { defaultValue: l.kind })}</td>
                    <td className="pr-3 font-mono text-xs">{l.recipient_masked}</td>
                    <td><Badge tone={l.status === "sent" ? "ok" : "bad"}>{t(`email.log.${l.status}`)}</Badge>{l.detail && <span className="ml-2 text-xs text-muted">{l.detail}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
    </Card>
  );
}
