import { api, DataTable, formatDate, PageHeader, Pager, unwrap, usePagedList, useTranslation } from "@/sdk";

import { SupplierName } from "../components/names";

export default function ReturnsPage() {
  const { t } = useTranslation("purchasing");
  const list = usePagedList(["purchasing", "returns"], (limit, offset) => unwrap(api.GET("/api/v1/purchasing/returns", { params: { query: { limit, offset } } })));
  return (
    <>
      <PageHeader title={t("returnsCredits")} description={t("returnsHint")} />
      <DataTable rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(r) => r.id} rowHref={(r) => `/returns/${r.id}`}
        empty={{ title: t("noReturns"), hint: t("noReturnsHint") }}
        columns={[
          { header: t("number"), cell: (r) => <span className="font-mono text-xs font-medium">{r.number}</span> },
          { header: t("supplier"), cell: (r) => <SupplierName id={r.supplier_id} /> },
          { header: t("date"), sortValue: (r) => r.returned_at, cell: (r) => formatDate(r.returned_at, true) },
          { header: t("note"), hideBelow: "md", cell: (r) => r.note ?? "—" },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />} />
    </>
  );
}
