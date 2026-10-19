import { Badge, DataTable, formatDate, usePagedList, Pager, api, unwrap, useTranslation } from "@/sdk";

import type { Profile } from "../hooks";

const TONE = { allow: "ok", warn: "warn", deny: "bad" } as const;

/** Every time this person came to the door, and what the door said. */
export function VisitsTab({ customerId, companyId, profile }: { customerId: string; companyId: string; profile: Profile | null }) {
  const { t } = useTranslation("memberships");
  const list = usePagedList(["memberships", "checkin", "visits", customerId], (limit, offset) =>
    unwrap(api.GET("/api/v1/memberships/checkin/recent", { params: { query: { company_id: companyId, customer_id: customerId, limit, offset } } })), 25, !!companyId);
  return (
    <div className="space-y-3">
      {profile?.last_visit_on && <p className="text-sm text-muted">{t("person.lastVisit", { date: formatDate(profile.last_visit_on) })}</p>}
      <DataTable rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(r) => r.id}
        empty={{ title: t("visits.empty"), hint: t("visits.emptyHint") }}
        columns={[
          { header: t("date"), sortValue: (r) => r.occurred_at, cell: (r) => formatDate(r.occurred_at, true) },
          { header: t("visits.result"), cell: (r) => {
            const d = r.decision === "allow" || r.decision === "warn" ? r.decision : "deny";
            return <Badge tone={TONE[d]}>{r.overridden ? t("checkin.overriddenShort") : t(`checkin.banner.${d}`)}</Badge>;
          } },
          { header: t("visits.how"), hideBelow: "sm", cell: (r) => t(`visits.methods.${r.method}`, r.method) },
          { header: t("note"), hideBelow: "md", cell: (r) => (r.overridden && r.override_reason ? r.override_reason : r.reasons[0]?.message ?? "—") },
          { header: "", hideBelow: "md", cell: (r) => (r.offline ? <Badge tone="info">{t("checkin.wasOffline")}</Badge> : null) },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />} />
    </div>
  );
}
