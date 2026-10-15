import { Copy } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  Alert, api, Badge, Button, Checkbox, DataTable, DetailList, Drawer, formatDate, humanise, PageHeader, Pager, quantity, Schemas, toast, unwrap, useCan, usePagedList, useTranslation,
} from "@/sdk";

import { useDeviceName, useMoney } from "../hooks";
import { CustomerName, ProductName } from "./hooks";
import { readRejectedSale, rejectedSaleTotal } from "./lib";

type Rejection = Schemas["RejectionOut"];

/** Sales and till operations from offline tills that the server refused. A manager reads why; the till keeps them and sends them again. */
export default function RejectionsPage() {
  const { t } = useTranslation("pos");
  const [params, setParams] = useSearchParams();
  const openId = params.get("open");
  const canExceptions = useCan("exceptions.manage");
  const [resolved, setResolved] = useState(false);
  const deviceName = useDeviceName();
  const list = usePagedList(["pos-rejections", resolved], (limit, offset) =>
    unwrap(api.GET("/api/v1/pos/sync/rejections", { params: { query: { include_resolved: resolved, limit, offset } } })));
  const open = list.rows?.find((r) => r.id === openId) ?? null;

  return (
    <>
      <PageHeader title={t("docs.rejections.title")} description={t("docs.rejections.hint")}
        actions={canExceptions && <Link to="/admin/exceptions"><Button variant="secondary">{t("docs.rejections.exceptions")}</Button></Link>} />
      <Alert tone="info" className="mb-4">{t("docs.rejections.readOnly")}</Alert>
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
        rowKey={(r) => r.id} rowHref={(r) => `/pos/sync/rejections?open=${r.id}`}
        toolbar={<Checkbox label={t("docs.rejections.showResolved")} checked={resolved} onChange={(e) => setResolved(e.target.checked)} />}
        empty={{ title: resolved ? t("docs.rejections.none") : t("docs.rejections.noneOpen"), hint: t("docs.rejections.noneHint") }}
        columns={[
          { header: t("when"), cell: (r) => formatDate(r.created_at, true) },
          { header: t("docs.rejections.device"), hideBelow: "sm", cell: (r) => deviceName(r.device_id) },
          { header: t("docs.rejections.kind"), hideBelow: "md", cell: (r) => t(`docs.rejections.op.${r.op_type}`, humanise(r.op_type)) },
          { header: t("docs.rejections.sale"), hideBelow: "lg", cell: (r) => <span className="font-mono text-xs">{readRejectedSale(r.payload).number ?? "—"}</span> },
          { header: t("docs.rejections.reason"), cell: (r) => <span className="line-clamp-2 text-sm">{r.error}</span> },
          { header: t("status"), cell: (r) => (r.resolved_at ? <Badge tone="ok">{t("docs.rejections.resolved")}</Badge> : <Badge tone="bad">{t("docs.rejections.needsAction")}</Badge>) },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      {open && <RejectionDetail rejection={open} onClose={() => setParams({}, { replace: true })} />}
    </>
  );
}

function RejectionDetail({ rejection, onClose }: { rejection: Rejection; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const m = useMoney();
  const deviceName = useDeviceName();
  const sale = readRejectedSale(rejection.payload);
  const total = rejectedSaleTotal(sale);
  const copy = () => {
    const text = JSON.stringify({ id: rejection.id, local_id: rejection.local_id, error: rejection.error, attempts: rejection.attempts, payload: rejection.payload }, null, 2);
    navigator.clipboard.writeText(text).then(() => toast(t("docs.rejections.copied"), "ok"), () => toast(t("docs.rejections.copyFailed"), "bad"));
  };

  return (
    <Drawer open onClose={onClose} title={t("docs.rejections.detailTitle")}
      footer={<><Button variant="secondary" onClick={copy}><Copy className="h-4 w-4" />{t("docs.rejections.copy")}</Button><Button onClick={onClose}>{t("close")}</Button></>}>
      <div className="space-y-4">
        <Alert tone={rejection.resolved_at ? "info" : "bad"}>{rejection.error}</Alert>
        <DetailList items={[
          { label: t("docs.rejections.device"), value: deviceName(rejection.device_id) },
          { label: t("docs.rejections.kind"), value: t(`docs.rejections.op.${rejection.op_type}`, humanise(rejection.op_type)) },
          { label: t("docs.rejections.madeAt"), value: sale.at ? formatDate(sale.at, true) : "—" },
          { label: t("docs.rejections.received"), value: formatDate(rejection.created_at, true) },
          { label: t("docs.rejections.attempts"), value: rejection.attempts },
          { label: t("docs.rejections.sale"), value: sale.number ?? "—" },
          ...(sale.customerId ? [{ label: t("docs.customer"), value: <CustomerName id={sale.customerId} /> }] : []),
          ...(rejection.resolved_at ? [{ label: t("docs.rejections.resolvedAt"), value: formatDate(rejection.resolved_at, true) }] : []),
        ]} />
        {sale.lines.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-semibold">{t("items")}</h3>
            <ul className="divide-y divide-line rounded-lg border border-line text-sm">
              {sale.lines.map((l, i) => (
                <li key={i} className="flex items-center justify-between gap-3 p-3">
                  <ProductName id={l.productId} />
                  <span className="tnum text-muted">{quantity(l.quantity)}{l.unitPrice != null && ` × ${m(l.unitPrice)}`}</span>
                </li>
              ))}
            </ul>
            {total && <p className="mt-2 text-right text-sm text-muted">{t("docs.rejections.chargedAtTill")}: <span className="tnum font-medium text-ink">{m(total)}</span></p>}
          </div>
        )}
        {sale.payments.length > 0 && (
          <div>
            <h3 className="mb-2 text-sm font-semibold">{t("payments")}</h3>
            <ul className="divide-y divide-line rounded-lg border border-line text-sm">
              {sale.payments.map((p, i) => (
                <li key={i} className="flex items-center justify-between gap-3 p-3">
                  <span>{t(`methods.${p.method}`, humanise(p.method))}{p.reference && <span className="ml-2 font-mono text-xs text-muted">{p.reference}</span>}</span>
                  <span className="tnum">{m(p.amount)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <Alert tone="info">{t("docs.rejections.whatNext")}</Alert>
      </div>
    </Drawer>
  );
}
