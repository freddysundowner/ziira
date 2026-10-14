import { api, Badge, Card, DataTable, EmptyState, humanise, unwrap, useQuery, useTranslation } from "@/sdk";

import { asRetention } from "./model";

/** What each unit keeps about people and for how long, with the company's retention settings. */
export default function RetentionTab({ companyId }: { companyId: string | undefined }) {
  const { t } = useTranslation("kernel");
  const view = useQuery({
    enabled: !!companyId, queryKey: ["privacy-retention", companyId],
    queryFn: async () => asRetention(await unwrap(api.GET("/api/v1/privacy/retention", { params: { query: { company_id: companyId! } } }))),
  });
  if (!companyId) return <EmptyState title={t("noCompany")} />;
  const data = view.data;
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">{t("dsr.retentionHint")}</p>
      <DataTable
        rows={data?.rules} loading={view.isLoading} error={view.error?.message} onRetry={() => void view.refetch()} rowKey={(r) => `${r.unit}:${r.code}`}
        searchText={(r) => `${r.unit} ${r.what} ${r.basis}`} searchPlaceholder={t("dsr.searchRetention")}
        empty={{ title: t("dsr.noRetention") }}
        columns={[
          { header: t("dsr.unit"), sortValue: (r) => r.unit, cell: (r) => <span className="font-medium">{t(`dsr.source.${r.unit}`, { defaultValue: humanise(r.unit) })}</span> },
          { header: t("dsr.what"), cell: (r) => <><span>{r.what}</span><span className="block text-xs text-muted">{r.basis}</span></> },
          { header: t("dsr.period"), cell: (r) => <>{r.period}{r.setting && <span className="block text-xs text-muted">{t("dsr.setBy", { setting: t(`set.${r.setting}`, { defaultValue: humanise(r.setting) }) })}</span>}</> },
          { header: t("dsr.atEnd"), hideBelow: "sm", cell: (r) => t(`dsr.atEndName.${r.at_end}`, { defaultValue: humanise(r.at_end) }) },
          { header: t("dsr.pastPeriod"), hideBelow: "md", align: "right", cell: (r) => (r.eligible > 0 ? <Badge tone="warn">{r.eligible}</Badge> : "0") },
        ]}
      />
      {data && data.never_deleted.length > 0 && (
        <Card title={t("dsr.neverDeleted")} description={t("dsr.neverDeletedHint")}>
          <ul className="list-inside list-disc text-sm">{data.never_deleted.map((x) => <li key={x}>{x}</li>)}</ul>
        </Card>
      )}
    </div>
  );
}
