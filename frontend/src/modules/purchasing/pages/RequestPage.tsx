import { Link, useParams } from "react-router-dom";

import { api, Button, Card, DataTable, DetailList, ErrorState, formatDate, PageHeader, quantity, Skeleton, toast, unwrap, useCan, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import { ApprovalBar } from "../components/ApprovalBar";
import { ProductName } from "../components/names";
import { Status } from "../components/Status";

export default function RequestPage() {
  const { t } = useTranslation("purchasing");
  const { requestId = "" } = useParams();
  const qc = useQueryClient();
  const canOrder = useCan("po.create");
  const request = useQuery({ queryKey: ["purchasing", "request", requestId], queryFn: () => unwrap(api.GET("/api/v1/purchasing/requests/{request_id}", { params: { path: { request_id: requestId } } })) });
  const submit = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/purchasing/requests/{request_id}/submit", { params: { path: { request_id: requestId } } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["purchasing"] }); toast(t("requestSubmitted"), "ok"); },
  });
  const r = request.data;
  if (request.error) return <ErrorState title={t("requestNotFound")} message={request.error.message} onRetry={() => void request.refetch()} />;
  if (!r) return <Skeleton className="h-40 w-full" />;
  return (
    <>
      <PageHeader back={{ to: "/requests", label: t("requests") }} title={t("requestTitle", { number: r.number })} description={<Status status={r.status} />}
        actions={<>
          {canOrder && r.status === "draft" && <Button loading={submit.isPending} onClick={() => submit.mutate()}>{t("submitForApproval")}</Button>}
          {canOrder && r.status === "approved" && <Link to={`/orders/new?request=${r.id}`}><Button>{t("createOrder")}</Button></Link>}
        </>} />
      <ApprovalBar docType="purchase_request" docId={r.id} waiting={r.status === "pending_approval"} />
      <div className="space-y-4">
        <Card><DetailList items={[{ label: t("neededBy"), value: formatDate(r.needed_by) }, { label: t("status"), value: <Status status={r.status} /> }]} /></Card>
        <Card title={t("lines")} flush>
          <DataTable rows={r.lines} rowKey={(l) => l.id} empty={{ title: t("noLines") }}
            columns={[
              { header: t("product"), cell: (l) => <ProductName id={l.product_id} /> },
              { header: t("quantity"), align: "right", cell: (l) => quantity(l.quantity) },
              { header: t("note"), hideBelow: "sm", cell: (l) => l.note ?? "—" },
            ]} />
        </Card>
      </div>
    </>
  );
}
