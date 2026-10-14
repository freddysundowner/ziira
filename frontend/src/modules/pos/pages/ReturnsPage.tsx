import { useState } from "react";
import { Link } from "react-router-dom";

import {
  api, DataTable, ErrorState, formatDate, humanise, Modal, Button, Pager, PageHeader, quantity, Schemas, Select, Skeleton, StatusBadge, unwrap,
  usePagedList, useQuery, useTranslation,
} from "@/sdk";

import { useBranches, useMoney } from "../hooks";

type ReturnSummary = Schemas["ziira__modules__pos__api__schemas__ReturnSummaryOut"];
const STATUSES = ["posted", "pending_approval", "rejected"] as const;

/** Goods taken back, with the ones still waiting for a manager's approval. */
export default function ReturnsPage() {
  const { t } = useTranslation("pos");
  const [branch, setBranch] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<ReturnSummary | null>(null);
  const { branches, nameOf } = useBranches();
  const m = useMoney();
  const list = usePagedList(["pos-returns", branch, status], (limit, offset) =>
    unwrap(api.GET("/api/v1/pos/returns", { params: { query: { branch_id: branch || undefined, status: status || undefined, limit, offset } } })));

  return (
    <>
      <PageHeader title={t("returns")} description={t("returnsHint")} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(r) => r.id}
        toolbar={(
          <>
            {branches.length > 1 && (
              <Select className="w-40" aria-label={t("branch")} value={branch} onChange={(e) => setBranch(e.target.value)}>
                <option value="">{t("allBranches")}</option>
                {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </Select>
            )}
            <Select className="w-44" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>
              {STATUSES.map((s) => <option key={s} value={s}>{t(`returnStatus.${s}`)}</option>)}
            </Select>
          </>
        )}
        empty={{ title: status || branch ? t("noReturnsMatch") : t("noReturns"), hint: status || branch ? t("tryOtherFilters") : t("noReturnsHint") }}
        columns={[
          { header: t("number"), cell: (r) => <button className="font-mono text-xs font-medium text-brand-strong hover:underline" onClick={() => setOpen(r)}>{r.number}</button> },
          { header: t("businessDate"), hideBelow: "sm", cell: (r) => formatDate(r.business_date) },
          { header: t("branch"), hideBelow: "lg", cell: (r) => nameOf(r.branch_id) },
          { header: t("refundMethod"), hideBelow: "md", cell: (r) => t(`refundMethods.${r.refund_method}`, humanise(r.refund_method)) },
          { header: t("sale"), hideBelow: "md", cell: (r) => (r.original_sale_id ? <Link className="text-brand-strong hover:underline" to={`/pos/sales/${r.original_sale_id}`}>{t("viewSale")}</Link> : "—") },
          { header: t("total"), align: "right", cell: (r) => m(r.total, r.company_id) },
          { header: t("status"), cell: (r) => <StatusBadge status={r.status} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      {open && <ReturnDetail summary={open} onClose={() => setOpen(null)} />}
    </>
  );
}

function ReturnDetail({ summary, onClose }: { summary: ReturnSummary; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const m = useMoney();
  const detail = useQuery({ queryKey: ["pos-return", summary.id], queryFn: () => unwrap(api.GET("/api/v1/pos/returns/{return_id}", { params: { path: { return_id: summary.id } } })) });
  return (
    <Modal open onClose={onClose} title={t("returnTitle", { number: summary.number })}
      footer={<>{summary.original_sale_id && <Link to={`/pos/sales/${summary.original_sale_id}`}><Button variant="secondary">{t("viewSale")}</Button></Link>}<Button onClick={onClose}>{t("close")}</Button></>}>
      {detail.error ? <ErrorState message={detail.error.message} onRetry={() => void detail.refetch()} />
        : !detail.data ? <Skeleton className="h-32 w-full" />
        : (
          <DataTable rows={detail.data.lines} rowKey={(l) => l.id} empty={{ title: t("noItems") }}
            columns={[
              { header: t("item"), cell: (l) => <ProductName id={l.product_id} /> },
              { header: t("qty"), align: "right", cell: (l) => quantity(l.quantity) },
              { header: t("tax"), hideBelow: "sm", align: "right", cell: (l) => m(l.tax_amount, summary.company_id) },
              { header: t("amount"), align: "right", cell: (l) => m(l.line_total, summary.company_id) },
            ]} />
        )}
    </Modal>
  );
}

/** A product's name from its id; a short id when the user may not read products. */
function ProductName({ id }: { id: string }) {
  const product = useQuery({ retry: false, staleTime: 5 * 60_000, queryKey: ["product-name", id], queryFn: () => unwrap(api.GET("/api/v1/products/products/{product_id}", { params: { path: { product_id: id } } })) });
  return <span className="font-medium">{product.data?.name ?? id.slice(0, 8)}</span>;
}
