import { Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, Button, DataTable, formatDate, PageHeader, Pager, Select, unwrap, useCan, usePagedList, useTranslation } from "@/sdk";

import { RequestDrawer } from "../components/RequestDrawer";
import { Status } from "../components/Status";

const STATUSES = ["draft", "pending_approval", "approved", "ordered"] as const;

export default function RequestsPage() {
  const { t } = useTranslation("purchasing");
  const navigate = useNavigate();
  const canOrder = useCan("po.create");
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState("");
  const list = usePagedList(["purchasing", "requests", status], (limit, offset) =>
    unwrap(api.GET("/api/v1/purchasing/requests", { params: { query: { status: status || undefined, limit, offset } } })));
  return (
    <>
      <PageHeader title={t("requests")} description={t("requestsHint")} actions={canOrder && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newRequest")}</Button>} />
      <DataTable rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(r) => r.id} rowHref={(r) => `/requests/${r.id}`}
        toolbar={<Select className="w-48" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}><option value="">{t("allStatuses")}</option>{STATUSES.map((s) => <option key={s} value={s}>{t(`statuses.${s}`)}</option>)}</Select>}
        empty={{ title: status ? t("noRequestMatch") : t("noRequests"), hint: status ? undefined : t("noRequestsHint"), action: canOrder && !status ? <Button onClick={() => setCreating(true)}>{t("newRequest")}</Button> : undefined }}
        columns={[
          { header: t("number"), cell: (r) => <span className="font-mono text-xs font-medium">{r.number}</span> },
          { header: t("neededBy"), hideBelow: "sm", cell: (r) => formatDate(r.needed_by) },
          { header: t("status"), cell: (r) => <Status status={r.status} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />} />
      {creating && <RequestDrawer onClose={() => setCreating(false)} onSaved={(id) => navigate(`/requests/${id}`)} />}
    </>
  );
}
