import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, Card, type Column, DataTable, ErrorState, formatDate, PageHeader, type Schemas, Skeleton, Stat, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../client";
import { ageLabel, backupTone } from "../lib";
import { UpgradeAllDialog } from "./UpgradeAllDialog";

type Task = Schemas["RecurringTask"];

export default function HealthPage() {
  const { t } = useTranslation("operator");
  const [upgrading, setUpgrading] = useState(false);
  const health = useQuery({ queryKey: ["operator", "health"], queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/health")), refetchInterval: 60_000 });

  if (health.isPending) {
    return <><PageHeader title={t("health.title")} /><div className="grid gap-3 sm:grid-cols-4"><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /><Skeleton className="h-24" /></div></>;
  }
  if (health.isError) return <><PageHeader title={t("health.title")} /><ErrorState title={t("health.loadFailed")} message={health.error.message} onRetry={() => void health.refetch()} /></>;

  const h = health.data;
  const behind = h.businesses_behind;
  const taskColumns: Column<Task>[] = [
    { header: t("health.task"), cell: (x) => <span className="font-mono text-xs">{x.name}</span>, sortValue: (x) => x.name },
    { header: t("health.oldestRun"), align: "right", cell: (x) => <span className="tnum text-sm">{ageLabel(x.oldest_run_age_seconds)}</span>, sortValue: (x) => x.oldest_run_age_seconds },
    { header: t("health.failing"), align: "right", cell: (x) => (x.failing_businesses ? <Badge tone="bad">{x.failing_businesses}</Badge> : <span className="text-sm text-muted">0</span>) },
  ];

  return (
    <>
      <PageHeader title={t("health.title")} description={t("health.description")}
        actions={<Button variant="secondary" onClick={() => void health.refetch()} loading={health.isFetching}>{t("health.refresh")}</Button>} />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label={t("health.ready")} value={h.ready ? t("health.yes") : t("health.no")} tone={h.ready ? "ok" : "bad"} hint={h.ready ? undefined : t("health.problemCount", { count: h.problems.length })} />
        <Stat label={t("health.businesses")} value={h.businesses_total} hint={t("health.behindCount", { count: behind.length })} tone={behind.length ? undefined : "ok"} />
        <Stat label={t("health.backup")} value={h.backups.reported ? ageLabel((h.backups.master_age_hours ?? 0) * 3600) : t("health.notReported")}
          tone={h.backups.reported && backupTone(h.backups.master_age_hours) === "ok" ? "ok" : h.backups.reported ? "bad" : undefined} hint={t("health.backupHint")} />
        <Stat label={t("health.jobsFailed")} value={h.queues?.jobs_failed ?? "-"} tone={h.queues ? (h.queues.jobs_failed ? "bad" : "ok") : undefined} hint={h.queues ? t("health.outboxHint", { pending: h.queues.outbox_pending, stuck: h.queues.outbox_stuck }) : undefined} />
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card title={t("health.readiness")}>
          {h.problems.length === 0
            ? <Alert tone="ok">{t("health.readyText")}</Alert>
            : <Alert tone="bad"><ul className="list-disc space-y-1 pl-4">{h.problems.map((p) => <li key={p}>{p}</li>)}</ul></Alert>}
          {h.master_migrations_pending.length > 0 && <Alert tone="warn" className="mt-3">{t("health.masterPending", { list: h.master_migrations_pending.join(", ") })}</Alert>}
        </Card>

        <Card title={t("health.migrations")} description={t("health.migrationsHint")}
          actions={behind.length > 0 ? <Button onClick={() => setUpgrading(true)}>{t("health.upgradeAll", { count: behind.length })}</Button> : undefined}>
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
          {h.businesses_unreadable.length > 0 && (
            <Alert tone="bad" className="mt-3">{t("health.unreadable", { list: h.businesses_unreadable.map((b) => b.code).join(", ") })}</Alert>
          )}
        </Card>

        <Card title={t("health.backups")}>
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

        <Card title={t("health.registrations")}>
          <div className="flex gap-6 text-sm">
            <div><p className="tnum text-2xl font-semibold">{h.registrations.pending}</p><p className="text-xs text-muted">{t("health.pendingVerification")}</p></div>
            <div><p className="tnum text-2xl font-semibold">{h.registrations.expired}</p><p className="text-xs text-muted">{t("health.expiredUnverified")}</p></div>
          </div>
        </Card>
      </div>

      <h2 className="mb-2 mt-6 text-base font-semibold">{t("health.queues")}</h2>
      {h.queues ? (
        <>
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label={t("health.jobsDue")} value={h.queues.jobs_due} hint={t("health.oldest", { age: ageLabel(h.queues.jobs_oldest_due_seconds) })} />
            <Stat label={t("health.outboxPending")} value={h.queues.outbox_pending} hint={t("health.oldest", { age: ageLabel(h.queues.outbox_lag_seconds) })} />
            <Stat label={t("health.outboxStuck")} value={h.queues.outbox_stuck} tone={h.queues.outbox_stuck ? "bad" : "ok"} />
            <Stat label={t("health.notificationsQueued")} value={h.queues.notifications_queued} />
            <Stat label={t("health.notificationsFailed")} value={h.queues.notifications_failed} tone={h.queues.notifications_failed ? "bad" : "ok"} />
            <Stat label={t("health.checkFailures")} value={h.queues.intel_check_failures} tone={h.queues.intel_check_failures ? "bad" : "ok"} />
          </div>
          <div className="mt-3">
            <DataTable rows={h.queues.recurring} columns={taskColumns} rowKey={(x) => x.name} dense empty={{ title: t("health.noTasks"), hint: t("health.noTasksHint") }} />
          </div>
        </>
      ) : <Alert tone="warn">{t("health.queuesUnavailable")}</Alert>}

      <h2 className="mb-2 mt-6 text-base font-semibold">{t("health.plugins")}</h2>
      <Card>
        <PluginList plugins={h.plugins} />
      </Card>

      {upgrading && <UpgradeAllDialog targets={behind} onClose={() => { setUpgrading(false); void health.refetch(); }} />}
    </>
  );
}

function PluginList({ plugins }: { plugins: Schemas["PluginStatus"] }) {
  const { t } = useTranslation("operator");
  if (plugins.folders.length === 0) return <p className="text-sm text-muted">{t("health.noExtraFolders")}</p>;
  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-muted">{t("health.extraFolders", { count: plugins.folders.length })}{plugins.production_allow_list ? ` ${t("health.allowListOn")}` : ""}</p>
      {plugins.loaded.length === 0 && plugins.refused.length === 0 && <p className="text-muted">{t("health.noExtraPlugins")}</p>}
      {plugins.loaded.length > 0 && (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {plugins.loaded.map((p) => (
            <li key={p.name} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <span>{p.title} <span className="font-mono text-xs text-muted">{p.name} {p.version}</span></span>
              <span className="flex gap-1">
                <Badge tone={p.manifest_checksum_ok ? "ok" : "bad"}>{t(p.manifest_checksum_ok ? "health.checksumOk" : "health.checksumBad")}</Badge>
                <Badge tone={p.on_allow_list ? "ok" : "neutral"}>{t(p.on_allow_list ? "health.allowed" : "health.notListed")}</Badge>
                <Badge tone={p.pinned ? "ok" : "warn"}>{t(p.pinned ? "health.pinned" : "health.notPinned")}</Badge>
              </span>
            </li>
          ))}
        </ul>
      )}
      {plugins.refused.map((p) => <Alert key={p.name} tone="bad"><strong>{p.name}</strong>: {p.reason}</Alert>)}
    </div>
  );
}
