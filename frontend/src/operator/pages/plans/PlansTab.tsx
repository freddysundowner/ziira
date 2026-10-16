import { Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Badge, type Column, DataTable, Select, useTranslation } from "@/sdk";

import type { PlatformSchema } from "../../types";
import { usePlans } from "../../catalog";
import { useOperatorCan } from "../../me";

type Plan = PlatformSchema<"PlanOut">;

export default function PlansTab() {
  const { t } = useTranslation("operator");
  const canEdit = useOperatorCan("platform.plans");
  const [status, setStatus] = useState("");
  const plans = usePlans();
  const rows = plans.data?.filter((p) => !status || p.status === status);
  const unlimited = t("plans.unlimited");

  const columns: Column<Plan>[] = [
    { header: t("plans.plan"), sortValue: (p) => p.sort_order, cell: (p) => <div className="min-w-0"><p className="truncate font-medium">{p.name}</p><p className="truncate font-mono text-xs text-muted">{p.code}</p></div> },
    { header: t("plans.edition"), hideBelow: "md", cell: (p) => <span className="text-sm">{p.edition ?? "-"}</span> },
    { header: t("plans.units"), align: "right", hideBelow: "md", cell: (p) => <span className="tnum text-sm" title={p.units.join(", ")}>{p.units.length}{p.addon_units.length > 0 && <span className="text-muted"> +{p.addon_units.length}</span>}</span> },
    {
      header: t("plans.limits"), hideBelow: "lg",
      cell: (p) => <span className="text-xs text-muted">{t("plans.limitsLine", { users: p.max_users ?? unlimited, branches: p.max_branches ?? unlimited, companies: p.max_companies ?? unlimited })}</span>,
    },
    { header: t("plans.trial"), align: "right", hideBelow: "lg", cell: (p) => <span className="tnum text-sm">{p.trial_days > 0 ? t("plans.trialDays", { count: p.trial_days }) : "-"}</span> },
    { header: t("plans.visibility"), hideBelow: "sm", cell: (p) => <Badge tone={p.is_public ? "info" : "neutral"}>{t(p.is_public ? "plans.public" : "plans.hidden")}</Badge> },
    { header: t("plans.status"), cell: (p) => <Badge tone={p.status === "active" ? "ok" : "neutral"}>{t(`plans.statuses.${p.status}`, p.status)}</Badge> },
    { header: t("plans.subscribers"), align: "right", sortValue: (p) => p.subscribers, cell: (p) => <span className="tnum text-sm">{p.subscribers}</span> },
  ];

  return (
    <DataTable
      rows={rows}
      columns={columns}
      rowKey={(p) => p.code}
      rowHref={(p) => `/operator/plans/edit/${encodeURIComponent(p.code)}`}
      loading={plans.isPending}
      error={plans.isError ? plans.error.message : null}
      onRetry={() => void plans.refetch()}
      searchText={(p) => `${p.name} ${p.code}`}
      searchPlaceholder={t("plans.search")}
      empty={{ title: t("plans.empty"), hint: canEdit ? t("plans.emptyHint") : undefined }}
      toolbar={(
        <>
          <Select aria-label={t("plans.filterStatus")} value={status} onChange={(e) => setStatus(e.target.value)} className="w-40">
            <option value="">{t("plans.allStatuses")}</option>
            <option value="active">{t("plans.statuses.active")}</option>
            <option value="retired">{t("plans.statuses.retired")}</option>
          </Select>
          {canEdit && <Link to="/operator/plans/new" className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-lg bg-brand-strong px-2.5 text-xs font-medium text-brand-ink shadow-card hover:bg-brand-strong/90"><Plus className="h-4 w-4" /> {t("plans.new")}</Link>}
        </>
      )}
    />
  );
}
