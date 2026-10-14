import { RefreshCw, Send } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, DataTable, Drawer, formatDate, PageHeader, Pager, Select, Spinner, unwrap, useCan, usePagedList, useTranslation,
} from "@/sdk";

import { Amount } from "../components/Amount";
import { IntentStatus } from "../components/IntentStatus";
import { NewRequest } from "../components/NewRequest";
import { useAutoRefresh } from "../components/useAutoRefresh";
import { usePaymentAccounts } from "../components/usePaymentAccounts";
import { FINAL_INTENT, hasPending, intentTone } from "../logic";

/** Payment prompts sent to customers' phones and how each ended. The list refreshes by itself while any is still pending. */
export default function RequestsPage() {
  const { t } = useTranslation("payments");
  const canCollect = useCan("payments.collect");
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const accounts = usePaymentAccounts({ includeInactive: true });
  const list = usePagedList(["payment-intents", status], (limit, offset) =>
    unwrap(api.GET("/api/v1/payments/intents", { params: { query: { status: status || undefined, limit, offset } } })));
  const pending = hasPending(list.rows);
  useAutoRefresh(pending, () => void list.query.refetch());

  return (
    <>
      <PageHeader title={t("requestsTitle")} description={t("requestsHint")}
        actions={canCollect && <Button onClick={() => setCreating(true)}><Send className="h-4 w-4" />{t("newRequest")}</Button>} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(i) => i.id}
        toolbar={
          <>
            <Select className="w-44" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>
              {["pending", ...FINAL_INTENT].map((s) => <option key={s} value={s}>{t(`intentStatuses.${s}`)}</option>)}
            </Select>
            {pending && <span className="flex items-center gap-1.5 text-xs text-muted"><Spinner />{t("refreshingWhilePending")}</span>}
            <Button size="sm" variant="ghost" className="ml-auto" onClick={() => void list.query.refetch()}><RefreshCw className="h-3.5 w-3.5" />{t("refresh")}</Button>
          </>
        }
        empty={{ title: status ? t("noMatch") : t("noRequests"), hint: status ? undefined : t("noRequestsHint"), action: canCollect && !status ? <Button onClick={() => setCreating(true)}>{t("newRequest")}</Button> : undefined }}
        columns={[
          { header: t("phone"), cell: (i) => <button className="tnum font-medium hover:underline" onClick={() => setOpenId(i.id)}>{i.phone_masked}</button> },
          { header: t("amount"), align: "right", cell: (i) => <Amount value={i.amount} companyId={accounts.data?.find((a) => a.id === i.payment_account_id)?.company_id} /> },
          { header: t("account"), hideBelow: "md", cell: (i) => accounts.data?.find((a) => a.id === i.payment_account_id)?.name ?? "—" },
          { header: t("receipt"), hideBelow: "sm", cell: (i) => <span className="font-mono text-xs">{i.receipt ?? "—"}</span> },
          { header: t("expires"), hideBelow: "lg", cell: (i) => (i.expires_at ? formatDate(i.expires_at, true) : "—") },
          { header: t("status"), cell: (i) => <Badge tone={intentTone(i.status)}>{t(`intentStatuses.${i.status}`, i.status)}</Badge> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <NewRequest open={creating} onClose={() => setCreating(false)} />
      {openId && (
        <Drawer open onClose={() => setOpenId(null)} title={t("requestDetail")}>
          <IntentStatus intentId={openId} companyId={accounts.data?.find((a) => a.id === list.rows?.find((i) => i.id === openId)?.payment_account_id)?.company_id} />
        </Drawer>
      )}
    </>
  );
}
