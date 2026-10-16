import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, Card, ErrorState, formatDate, PageHeader, Skeleton, Stat, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../client";
import { ageLabel, backupTone } from "../lib";
import { useOperatorCan } from "../me";
import { UpgradeAllDialog } from "./UpgradeAllDialog";

/** System > Backups and upgrades: how fresh the backups are, which businesses are behind on upgrades, and the button that brings them up to date. */
export default function BackupsPage() {
  const { t } = useTranslation("operator");
  const canUpgrade = useOperatorCan("platform.units");
  const [upgrading, setUpgrading] = useState(false);
  const health = useQuery({ queryKey: ["operator", "health"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/health")), refetchInterval: 60_000 });

  if (health.isPending) {
    return <><PageHeader title={t("backups.title")} /><div className="grid gap-3 sm:grid-cols-3"><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div></>;
  }
  if (health.isError) return <><PageHeader title={t("backups.title")} /><ErrorState title={t("health.loadFailed")} message={health.error.message} onRetry={() => void health.refetch()} /></>;
  const h = health.data;
  const behind = h.businesses_behind;
  return (
    <>
      <PageHeader title={t("backups.title")} description={t("backups.description")}
        actions={<Button variant="secondary" loading={health.isFetching && !health.isPending} onClick={() => void health.refetch()}>{t("health.refresh")}</Button>} />

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label={t("health.backup")} value={h.backups.reported ? ageLabel((h.backups.master_age_hours ?? 0) * 3600) : t("health.notReported")}
          tone={h.backups.reported && backupTone(h.backups.master_age_hours) === "ok" ? "ok" : h.backups.reported ? "bad" : undefined} hint={t("health.backupHint")} />
        <Stat label={t("backups.behind")} value={behind.length} tone={behind.length ? "bad" : "ok"} hint={t("backups.behindHint", { total: h.businesses_total })} />
        <Stat label={t("backups.unreadable")} value={h.businesses_unreadable.length} tone={h.businesses_unreadable.length ? "bad" : "ok"} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title={t("health.backups")} description={t("backups.backupsHint")}>
          {!h.backups.reported ? <Alert tone="warn">{t("health.backupsNotReported")}</Alert> : (
            <div className="space-y-2 text-sm">
              <p>{t("health.masterBackup")}: {h.backups.master_taken_at
                ? <><Badge tone={backupTone(h.backups.master_age_hours)}>{ageLabel((h.backups.master_age_hours ?? 0) * 3600)}</Badge> <span className="text-xs text-muted">{formatDate(h.backups.master_taken_at, true)}</span></>
                : <Badge tone="bad">{t("health.none")}</Badge>}</p>
              {h.backups.tenants_without_backup.length > 0
                ? <Alert tone="warn">{t("health.withoutBackup", { list: h.backups.tenants_without_backup.join(", ") })}</Alert>
                : <p className="text-muted">{t("health.everyBusinessBackedUp")}</p>}
            </div>
          )}
        </Card>

        <Card title={t("health.migrations")} description={t("health.migrationsHint")}
          actions={behind.length > 0 && canUpgrade ? <Button onClick={() => setUpgrading(true)}>{t("health.upgradeAll", { count: behind.length })}</Button> : undefined}>
          {behind.length === 0 ? <Alert tone="ok">{t("health.allCurrent")}</Alert> : (
            <ul className="divide-y divide-line rounded-lg border border-line">
              {behind.map((b) => (
                <li key={b.code} className="px-3 py-2 text-sm">
                  <span className="font-medium">{b.name}</span> <span className="font-mono text-xs text-muted">{b.code}</span>
                  <p className="text-xs text-muted">{Object.entries(b.behind).map(([unit, files]) => `${unit}: ${files.length}`).join(" · ")}</p>
                </li>
              ))}
            </ul>
          )}
          {h.master_migrations_pending.length > 0 && <Alert tone="warn" className="mt-3">{t("health.masterPending", { list: h.master_migrations_pending.join(", ") })}</Alert>}
          {h.businesses_unreadable.length > 0 && (
            <Alert tone="bad" className="mt-3">{t("health.unreadable", { list: h.businesses_unreadable.map((b) => b.code).join(", ") })}</Alert>
          )}
        </Card>
      </div>

      {upgrading && <UpgradeAllDialog targets={behind} onClose={() => { setUpgrading(false); void health.refetch(); }} />}
    </>
  );
}
