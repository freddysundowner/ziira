import { api, DataTable, formatDate, PageHeader, Pager, unwrap, usePagedList, useTranslation } from "@/sdk";

import { Money } from "../components/Money";
import { SupplierName } from "../components/names";

export default function CreditNotesPage() {
  const { t } = useTranslation("purchasing");
  const list = usePagedList(["purchasing", "credit-notes"], (limit, offset) => unwrap(api.GET("/api/v1/purchasing/credit-notes", { params: { query: { limit, offset } } })));
  return (
    <>
      <PageHeader title={t("creditNotes")} description={t("creditNotesHint")} />
      <DataTable rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(c) => c.id} rowHref={(c) => `/credit-notes/${c.id}`}
        empty={{ title: t("noCreditNotes"), hint: t("noCreditNotesHint") }}
        columns={[
          { header: t("number"), cell: (c) => <span className="font-mono text-xs font-medium">{c.number}</span> },
          { header: t("theirCreditNo"), cell: (c) => c.supplier_credit_no },
          { header: t("supplier"), hideBelow: "sm", cell: (c) => <SupplierName id={c.supplier_id} /> },
          { header: t("date"), hideBelow: "md", sortValue: (c) => c.credit_date, cell: (c) => formatDate(c.credit_date) },
          { header: t("total"), align: "right", cell: (c) => <Money value={c.total} companyId={c.company_id} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />} />
    </>
  );
}
