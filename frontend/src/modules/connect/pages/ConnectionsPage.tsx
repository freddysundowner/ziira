import { Link } from "react-router-dom";

import { api, Badge, Button, Card, DataTable, PageHeader, Select, unwrap, useCan, useCompany, useQuery, useTranslation } from "@/sdk";
import { useState } from "react";

import { CoveragePanel } from "../components/CoveragePanel";
import { OverlapBanner } from "../components/OverlapBanner";
import { StatusChip } from "../components/StatusChip";
import { when } from "../components/RunsTable";
import { isStale } from "../logic";

/** Connected systems: what is connected, how fresh it is, and what Intelligence can check because of it. */
export default function ConnectionsPage() {
  const { t } = useTranslation("connect");
  const canManage = useCan("connect.manage");
  const { companies, company } = useCompany();
  const [companyId, setCompanyId] = useState("");
  const chosen = companyId || company?.id || "";
  const list = useQuery({ queryKey: ["connect", "connections"], queryFn: () => unwrap(api.GET("/api/v1/connect/connections")), refetchInterval: 30_000 });
  const rows = (list.data ?? []).filter((c) => !chosen || c.company_id === chosen);
  return (
    <>
      <PageHeader title={t("title")} description={t("subtitle")}
        actions={canManage && <Link to="/connect/new"><Button>{t("add")}</Button></Link>} />
      {companies.length > 1 && (
        <div className="mb-4 max-w-xs"><Select aria-label={t("company")} value={chosen} onChange={(e) => setCompanyId(e.target.value)}>{companies.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></div>
      )}
      {chosen && <OverlapBanner companyId={chosen} />}
      <div className="space-y-5">
        <Card flush>
          <DataTable
            rows={rows} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()}
            rowKey={(c) => c.id} rowHref={(c) => `/connect/connections/${c.id}`}
            empty={{ title: t("empty"), hint: t("emptyHint"), action: canManage ? <Link to="/connect/new"><Button>{t("connectFirst")}</Button></Link> : undefined }}
            columns={[
              { header: t("list.name"), sortValue: (c) => c.name, cell: (c) => <><span className="font-medium">{c.name}</span><span className="block text-xs text-muted">{c.kind_title}</span></> },
              { header: t("list.status"), cell: (c) => <span className="inline-flex flex-wrap gap-1"><StatusChip status={c.status} />{isStale(c) && <Badge tone="warn">{t("list.stale")}</Badge>}</span> },
              { header: t("list.last"), hideBelow: "sm", sortValue: (c) => c.last_success_at, cell: (c) => when(c.last_success_at) },
              { header: t("list.reads"), hideBelow: "md", cell: (c) => <span className="text-xs text-muted">{c.entities.filter((e) => e.complete_at).map((e) => t(`entity.${e.entity}`, { defaultValue: e.entity })).join(", ") || "—"}</span> },
              { header: t("list.freshness"), hideBelow: "lg", cell: (c) => t(`freshness.${c.freshness}`) },
            ]}
          />
        </Card>
        {chosen && <Card title={t("coverage.title")} description={t("coverage.subtitle")}><CoveragePanel companyId={chosen} /></Card>}
      </div>
    </>
  );
}
