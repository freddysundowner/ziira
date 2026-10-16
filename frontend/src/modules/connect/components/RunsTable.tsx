import { api, Badge, type BadgeTone, DataTable, formatDate, Pager, unwrap, usePagedList, useTranslation } from "@/sdk";

const TONE: Record<string, BadgeTone> = { ok: "ok", partial: "warn", failed: "bad", running: "info" };
export const when = (iso: string | null | undefined) => formatDate(iso, true);

/** The history of reads: what was read, how much was new or changed, what was skipped and why. */
export function RunsTable({ connectionId }: { connectionId: string }) {
  const { t } = useTranslation("connect");
  const list = usePagedList(["connect", "runs", connectionId], (limit, offset) =>
    unwrap(api.GET("/api/v1/connect/connections/{connection_id}/runs", { params: { path: { connection_id: connectionId }, query: { limit, offset } } })), 20);
  return (
    <DataTable
      rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
      rowKey={(r) => r.id} empty={{ title: t("history.empty"), hint: t("history.emptyHint") }}
      footer={<Pager page={list.page} hasNext={list.hasNext} onPage={list.setPage} count={list.rows?.length ?? 0} />}
      columns={[
        { header: t("history.when"), cell: (r) => when(r.started_at) },
        { header: t("history.entity"), cell: (r) => t(`entity.${r.entity}`, { defaultValue: r.entity }) },
        { header: t("history.status"), cell: (r) => <Badge tone={TONE[r.status] ?? "neutral"}>{t(`run.${r.status}`)}</Badge> },
        { header: t("history.read"), align: "right", cell: (r) => <span className="tnum">{r.records_read}</span> },
        { header: t("history.new"), align: "right", hideBelow: "sm", cell: (r) => <span className="tnum">{r.records_new}</span> },
        { header: t("history.changed"), align: "right", hideBelow: "sm", cell: (r) => <span className="tnum">{r.records_changed}</span> },
        { header: t("history.skipped"), align: "right", hideBelow: "md", cell: (r) => <span className="tnum">{r.records_skipped}</span> },
        {
          header: t("history.details"), hideBelow: "md",
          cell: (r) => (
            <div className="max-w-sm space-y-0.5 text-xs">
              {r.error && <p className="text-bad">{r.error}</p>}
              {r.notes.slice(0, 4).map((n) => <p key={n} className="text-muted">{n}</p>)}
            </div>
          ),
        },
      ]}
    />
  );
}
