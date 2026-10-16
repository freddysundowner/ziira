import { useState } from "react";

import { api, DataTable, formatDate, Input, Pager, PageHeader, Select, StatusBadge, unwrap, usePagedList, useTranslation } from "@/sdk";

import { Variance } from "../components/Variance";
import { useBranches, useDeviceName, useMoney, useUserNames } from "../hooks";

/** Till sessions: who opened which till, when, and how the cash counted at the end compares with what was expected. */
export default function TillsPage() {
  const { t } = useTranslation("pos");
  const [branch, setBranch] = useState("");
  const [status, setStatus] = useState("");
  const [date, setDate] = useState("");
  const { branches, nameOf } = useBranches();
  const m = useMoney();
  const cashier = useUserNames();
  const deviceName = useDeviceName();
  const list = usePagedList(["pos-tills", branch, status, date], (limit, offset) =>
    unwrap(api.GET("/api/v1/pos/tills", { params: { query: { branch_id: branch || undefined, status: status || undefined, business_date: date || undefined, limit, offset } } })));
  const filtered = Boolean(branch || status || date);

  return (
    <>
      <PageHeader title={t("tillsDevices")} description={t("tillsHint")} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
        rowKey={(x) => x.id} rowHref={(x) => `/pos/tills/${x.id}`}
        toolbar={(
          <>
            <Input className="w-40" type="date" aria-label={t("businessDate")} value={date} onChange={(e) => setDate(e.target.value)} />
            {branches.length > 1 && (
              <Select className="w-40" aria-label={t("branch")} value={branch} onChange={(e) => setBranch(e.target.value)}>
                <option value="">{t("allBranches")}</option>
                {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
              </Select>
            )}
            <Select className="w-36" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>
              <option value="open">{t("tillStatus.open")}</option>
              <option value="closed">{t("tillStatus.closed")}</option>
            </Select>
          </>
        )}
        empty={{ title: filtered ? t("noTillsMatch") : t("noTills"), hint: filtered ? t("tryOtherFilters") : t("noTillsHint") }}
        columns={[
          { header: t("till"), cell: (x) => <span className="font-medium">{deviceName(x.device_id)}</span> },
          { header: t("businessDate"), cell: (x) => formatDate(x.business_date) },
          { header: t("cashier"), hideBelow: "md", cell: (x) => cashier(x.cashier_id) },
          { header: t("branch"), hideBelow: "lg", cell: (x) => nameOf(x.branch_id) },
          { header: t("openedAt"), hideBelow: "lg", cell: (x) => formatDate(x.opened_at, true) },
          { header: t("expectedCash"), hideBelow: "md", align: "right", cell: (x) => (x.expected_cash === null ? "—" : m(x.expected_cash)) },
          { header: t("variance"), hideBelow: "sm", align: "right", cell: (x) => <Variance value={x.variance} format={m} /> },
          { header: t("status"), cell: (x) => <StatusBadge status={x.status} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
    </>
  );
}
