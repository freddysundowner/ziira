import { X } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  api, Badge, Button, DataTable, formatDate, Input, Pager, PageHeader, Select, StatusBadge, unwrap, useDebounced, usePagedList, useTranslation,
} from "@/sdk";

import { useBranches, useDeviceName, useMoney, useTillOptions, useUserNames } from "../hooks";

const STATUSES = ["posted", "voided"] as const;

/** All sales, newest first, filtered by day, branch, till, status and receipt number. */
export default function SalesPage() {
  const { t } = useTranslation("pos");
  const [params, setParams] = useSearchParams();
  const till = params.get("till") ?? "";
  const [date, setDate] = useState("");
  const [branch, setBranch] = useState("");
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const number = useDebounced(search.trim());
  const { branches, nameOf } = useBranches();
  const m = useMoney();
  const cashier = useUserNames();
  const tills = useTillOptions({ branch, date });
  const deviceName = useDeviceName();

  const list = usePagedList(["pos-sales", number, date, branch, status, till], (limit, offset) =>
    unwrap(api.GET("/api/v1/pos/sales", { params: { query: {
      number: number || undefined, business_date: date || undefined, branch_id: branch || undefined, status: status || undefined,
      till_session_id: till || undefined, limit, offset } } })));
  const setTill = (id: string) => setParams(id ? { till: id } : {}, { replace: true });
  const filtered = Boolean(number || date || branch || status || till);

  return (
    <>
      <PageHeader title={t("sales")} description={t("salesHint")} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
        rowKey={(s) => s.id} rowHref={(s) => `/pos/sales/${s.id}`}
        toolbar={(
          <>
            <Input className="w-44" aria-label={t("searchNumber")} placeholder={t("searchNumber")} value={search} onChange={(e) => setSearch(e.target.value)} />
            <Input className="w-40" type="date" aria-label={t("businessDate")} value={date} onChange={(e) => setDate(e.target.value)} />
            {branches.length > 1 && (
              <Select className="w-40" aria-label={t("branch")} value={branch} onChange={(e) => setBranch(e.target.value)}>
                <option value="">{t("allBranches")}</option>
                {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </Select>
            )}
            <Select className="w-36" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>
              {STATUSES.map((s) => <option key={s} value={s}>{t(`saleStatus.${s}`)}</option>)}
            </Select>
            <Select className="w-48" aria-label={t("till")} value={till} onChange={(e) => setTill(e.target.value)}>
              <option value="">{t("allTills")}</option>
              {till && !tills.data?.some((x) => x.id === till) && <option value={till}>{t("selectedTill")}</option>}
              {(tills.data ?? []).map((x) => <option key={x.id} value={x.id}>{deviceName(x.device_id)} · {formatDate(x.business_date)}</option>)}
            </Select>
            {filtered && (
              <Button variant="ghost" onClick={() => { setSearch(""); setDate(""); setBranch(""); setStatus(""); setTill(""); }}><X className="h-4 w-4" />{t("clearFilters")}</Button>
            )}
          </>
        )}
        empty={{ title: filtered ? t("noSalesMatch") : t("noSales"), hint: filtered ? t("tryOtherFilters") : t("noSalesHint") }}
        columns={[
          { header: t("number"), cell: (s) => <span className="font-mono text-xs font-medium">{s.number}</span> },
          { header: t("when"), hideBelow: "sm", cell: (s) => formatDate(s.sold_at, true) },
          { header: t("branch"), hideBelow: "lg", cell: (s) => nameOf(s.branch_id) },
          { header: t("cashier"), hideBelow: "lg", cell: (s) => cashier(s.cashier_id) },
          { header: t("total"), align: "right", cell: (s) => m(s.total, s.company_id) },
          { header: t("status"), cell: (s) => (
            <span className="flex flex-wrap gap-1"><StatusBadge status={s.status} />{s.synced_offline && <Badge tone="info">{t("offline")}</Badge>}</span>
          ) },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
    </>
  );
}
