import { Link } from "react-router-dom";

import { Badge, Card, cx, ErrorState, formatDate, Skeleton, type Schemas, useTranslation } from "@/sdk";

import { personPath } from "../public";

type Row = Schemas["CheckinRowOut"];

const TONE = { allow: "ok", warn: "warn", deny: "bad" } as const;

/** The latest entries; refused ones stand out. */
export function RecentList({ rows, loading, error, onRetry }: { rows?: Row[]; loading: boolean; error?: string; onRetry: () => void }) {
  const { t } = useTranslation("memberships");
  return (
    <Card title={t("checkin.recent")} flush>
      {error ? <ErrorState message={error} onRetry={onRetry} />
        : loading || !rows ? <div className="space-y-2 p-4"><Skeleton className="h-10 w-full" /><Skeleton className="h-10 w-full" /><Skeleton className="h-10 w-full" /></div>
        : rows.length === 0 ? <p className="p-4 text-sm text-muted">{t("checkin.recentEmpty")}</p>
        : (
          <ul className="divide-y divide-line">
            {rows.map((r) => {
              const refused = r.decision === "deny" && !r.overridden;
              const decision = r.decision === "allow" || r.decision === "warn" ? r.decision : "deny";
              return (
                <li key={r.id} className={cx(refused && "bg-bad-soft")}>
                  <Link to={personPath(r.customer_id)} className="flex min-h-12 flex-wrap items-center justify-between gap-x-3 gap-y-1 px-4 py-2 text-sm hover:bg-sunken">
                    <span className="min-w-0">
                      <span className="font-medium [overflow-wrap:anywhere]">{r.customer_name ?? r.member_number ?? "—"}</span>
                      {r.member_number && <span className="ml-2 font-mono text-xs text-muted">{r.member_number}</span>}
                      {refused && r.reasons[0] && <span className="block text-xs text-bad [overflow-wrap:anywhere]">{r.reasons[0].message}</span>}
                      {r.overridden && r.override_reason && <span className="block text-xs text-muted [overflow-wrap:anywhere]">{t("checkin.letInBecause", { reason: r.override_reason })}</span>}
                    </span>
                    <span className="flex flex-wrap items-center gap-2">
                      {r.offline && <Badge tone="info">{t("checkin.wasOffline")}</Badge>}
                      <Badge tone={TONE[decision]}>{r.overridden ? t("checkin.overriddenShort") : t(`checkin.banner.${decision}`)}</Badge>
                      <span className="text-xs text-muted tnum">{formatDate(r.occurred_at, true)}</span>
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>)}
    </Card>
  );
}
