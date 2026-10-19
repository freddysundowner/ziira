import { Plus } from "lucide-react";

import { Link } from "react-router-dom";

import { api, DataTable, formatDate, Pager, PageHeader, StatusBadge, unwrap, usePagedList, useTranslation } from "@/sdk";

/** Earlier imports, with where each one stands. Opening one continues it or shows its report. */
export default function ImportsPage() {
  const { t } = useTranslation("imports");
  const list = usePagedList(["imports"], (limit, offset) => unwrap(api.GET("/api/v1/imports/batches", { params: { query: { limit, offset } } })), 20);
  const start = <Link to="/imports/new" className="inline-flex h-9 items-center gap-2 rounded-lg btn-gradient px-3 text-sm font-semibold"><Plus className="h-4 w-4" />{t("new")}</Link>;
  const guide = <Link to="/imports/opening-balances" className="inline-flex h-9 items-center rounded-lg border border-line px-3 text-sm font-medium hover:bg-sunken">{t("guide.link")}</Link>;
  return (
    <>
      <PageHeader title={t("title")} description={t("hint")} actions={<div className="flex gap-2">{guide}{start}</div>} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(b) => b.id}
        rowHref={(b) => `/imports/${b.id}`}
        empty={{ title: t("empty"), hint: t("emptyHint"), action: start }}
        columns={[
          { header: t("what"), cell: (b) => <span className="font-medium">{b.kind_title}</span> },
          { header: t("file"), hideBelow: "sm", cell: (b) => b.filename },
          { header: t("status"), cell: (b) => <StatusBadge status={b.status} /> },
          { header: t("rows"), hideBelow: "md", align: "right", cell: (b) => t("rowsSummary", { total: b.total_rows, imported: b.counts.imported }) },
          { header: t("when"), hideBelow: "lg", cell: (b) => formatDate(b.created_at, true) },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
    </>
  );
}
