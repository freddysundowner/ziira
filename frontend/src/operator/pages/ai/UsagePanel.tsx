import { useQuery } from "@tanstack/react-query";

import { Card, ErrorState, formatDate, Skeleton, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { barPercent, usd } from "../../helpers/ai";

/** This month's estimated use: per provider, per day (a simple bar each) and the ten busiest businesses. */
export function UsagePanel() {
  const { t } = useTranslation("operator");
  const usage = useQuery({ queryKey: ["operator", "ai", "usage"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/ai/usage")) });
  if (usage.isPending) return <Skeleton className="h-40 w-full" />;
  if (usage.isError) return <ErrorState title={t("ai.usage.loadFailed")} message={usage.error.message} onRetry={() => void usage.refetch()} />;
  const u = usage.data;
  const web = (u as { website_assistant?: typeof u.website_assistant }).website_assistant;      // absent from an API that is not updated yet
  const max = Math.max(0, ...u.days.map((d) => Number(d.cost_usd)));
  return (
    <Card title={t("ai.usage.title")} description={t("ai.usage.hint")}>
      {u.providers.length === 0 ? <p className="text-sm text-muted">{t("ai.usage.empty")}</p> : (
        <div className="space-y-5">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-muted"><th className="py-1">{t("ai.usage.provider")}</th><th>{t("ai.usage.calls")}</th><th>{t("ai.usage.tokensIn")}</th><th>{t("ai.usage.tokensOut")}</th><th className="text-right">{t("ai.usage.cost")}</th></tr></thead>
              <tbody>{u.providers.map((p) => (
                <tr key={p.provider} className="border-t border-line"><td className="py-1 font-medium">{p.provider}</td><td>{p.calls}</td><td>{p.tokens_in.toLocaleString()}</td><td>{p.tokens_out.toLocaleString()}</td><td className="text-right">{usd(p.cost_usd)}</td></tr>
              ))}</tbody>
            </table>
          </div>
          {web && web.calls > 0 && <p className="text-xs text-muted">{web.label}: {t("ai.websiteUsage", { calls: web.calls, cost: usd(web.cost_usd) })}</p>}
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{t("ai.usage.perDay")}</p>
            <ul className="space-y-1" aria-label={t("ai.usage.perDay")}>
              {u.days.map((d) => (
                <li key={d.day} className="flex items-center gap-2 text-xs">
                  <span className="w-20 shrink-0 text-muted">{formatDate(d.day)}</span>
                  <span className="h-3 rounded bg-brand" style={{ width: `${barPercent(d.cost_usd, max)}%` }} />
                  <span>{usd(d.cost_usd)}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{t("ai.usage.top")}</p>
            <ol className="space-y-1 text-sm">
              {u.top_businesses.map((b) => <li key={b.code} className="flex justify-between gap-2"><span>{b.name}</span><span className="text-muted">{t("ai.usage.businessLine", { calls: b.calls, cost: usd(b.cost_usd) })}</span></li>)}
            </ol>
          </div>
        </div>
      )}
    </Card>
  );
}
