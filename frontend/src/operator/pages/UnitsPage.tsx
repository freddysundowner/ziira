import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Badge, Button, type Column, DataTable, PageHeader, Select, type Schemas, formatDate, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../client";
import { actionsFor, STATUS_TONE, type UnitAction } from "../lib";
import { UnitActionDialog } from "./UnitActionDialog";

type Unit = Schemas["PlatformUnit"];

export default function UnitsPage() {
  const { t } = useTranslation("operator");
  const [filter, setFilter] = useState("");
  const [action, setAction] = useState<{ unit: Unit; action: UnitAction } | null>(null);
  const units = useQuery({ queryKey: ["operator", "units"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/units")) });

  const rows = (units.data ?? []).filter((u) => !filter || u.status === filter);
  const columns: Column<Unit>[] = [
    {
      header: t("units.unit"), sortValue: (u) => u.title,
      cell: (u) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{u.title}</p>
          <p className="truncate font-mono text-xs text-muted">{u.name}</p>
        </div>
      ),
    },
    {
      header: t("units.kind"), hideBelow: "md", sortValue: (u) => u.kind,
      cell: (u) => (
        <div className="flex flex-wrap gap-1">
          <Badge tone={u.kind === "kernel" ? "brand" : "neutral"}>{t(`units.kinds.${u.kind}`, u.kind)}</Badge>
          {u.source === "extra folder" && <Badge tone="info">{t("units.extra")}</Badge>}
          {u.category && <span className="text-xs text-muted">{u.category}</span>}
        </div>
      ),
    },
    {
      header: t("units.version"), hideBelow: "sm",
      cell: (u) => (
        <span className="tnum text-sm">
          {u.version_installed ?? "-"}
          {u.version_installed !== u.version_on_disk && <span className="text-muted"> {"->"} {u.version_on_disk}</span>}
        </span>
      ),
    },
    {
      header: t("units.status"), sortValue: (u) => u.status,
      cell: (u) => <Badge tone={STATUS_TONE[u.status] ?? "neutral"}>{t(`units.statuses.${u.status}`, u.status)}</Badge>,
    },
    {
      header: t("units.requires"), hideBelow: "lg",
      cell: (u) => <span className="text-xs text-muted">{u.requires.length ? u.requires.join(", ") : "-"}</span>,
    },
    {
      header: t("units.businesses"), hideBelow: "md", align: "right", sortValue: (u) => u.businesses_enabled,
      cell: (u) => (
        <span className="tnum text-sm" title={t("units.businessesHint", { enabled: u.businesses_enabled, holding: u.businesses_holding })}>
          {u.businesses_enabled}
          {u.businesses_behind > 0 && <Badge tone="warn" className="ml-1.5">{t("units.behind", { count: u.businesses_behind })}</Badge>}
        </span>
      ),
    },
    {
      header: "", align: "right",
      cell: (u) => (
        <div className="flex justify-end gap-1.5">
          {actionsFor(u).map((a) => (
            <Button key={a} size="sm" variant={a === "uninstall" ? "secondary" : "primary"} onClick={() => setAction({ unit: u, action: a })}
              aria-label={t("units.actionFor", { action: t(`units.actions.${a}`), unit: u.title })}>
              {t(`units.actions.${a}`)}
            </Button>
          ))}
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader title={t("units.title")} description={t("units.description")} />
      <DataTable
        rows={units.data ? rows : undefined}
        columns={columns}
        rowKey={(u) => u.name}
        loading={units.isPending}
        error={units.isError ? units.error.message : null}
        onRetry={() => void units.refetch()}
        searchText={(u) => `${u.title} ${u.name} ${u.category}`}
        searchPlaceholder={t("units.search")}
        empty={{ title: t("units.empty"), hint: t("units.emptyHint") }}
        toolbar={(
          <Select aria-label={t("units.statusFilter")} value={filter} onChange={(e) => setFilter(e.target.value)} className="w-44">
            <option value="">{t("units.allStatuses")}</option>
            {["available", "installed", "needs_upgrade"].map((s) => <option key={s} value={s}>{t(`units.statuses.${s}`)}</option>)}
          </Select>
        )}
        footer={units.data && units.dataUpdatedAt ? <p className="px-4 py-2 text-xs text-muted">{t("units.footer", { count: units.data.length, date: formatDate(new Date(units.dataUpdatedAt).toISOString(), true) })}</p> : undefined}
      />
      {action && <UnitActionDialog unit={action.unit} action={action.action} onClose={() => setAction(null)} />}
    </>
  );
}
