import { api, DataTable, formatDate, Pager, unwrap, usePagedList, useTranslation } from "@/sdk";

/** What support staff did in this business, newest first: read from the business's own audit log. */
export default function AccessLogTab() {
  const { t } = useTranslation("kernel");
  const list = usePagedList(["support-access-log"], (limit, offset) => unwrap(api.GET("/api/v1/support/access-log", { params: { query: { limit, offset } } })), 25);
  return (
    <DataTable
      rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(e) => String(e.id)}
      footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      empty={{ title: t("support.logNone"), hint: t("support.logNoneHint") }}
      columns={[
        { header: t("support.when"), cell: (e) => formatDate(e.occurred_at, true) },
        { header: t("support.who"), cell: (e) => e.operator ?? "—" },
        { header: t("support.what"), cell: (e) => t(`support.actionName.${e.action}`, { defaultValue: e.action }) },
        { header: "", hideBelow: "md", cell: (e) => <code className="text-xs text-muted">{detail(e.detail)}</code> },
      ]}
    />
  );
}

/** The method and route of a request, or the level and times of a session. */
function detail(d: Record<string, unknown>): string {
  if (d.method) return `${String(d.method)} ${String(d.route)} ${d.status ?? ""}`.trim();
  if (d.level) return String(d.level);
  return "";
}
