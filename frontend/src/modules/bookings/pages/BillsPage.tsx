import { Plus } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api, Badge, Button, Checkbox, type Column, DataTable, formatDate, Input, money, PageHeader, Select, today, unwrap, useMutation, useQuery, useTranslation } from "@/sdk";

import { BranchPicker } from "../components/BranchBar";
import { useBranch } from "../hooks";
import type { CheckoutListRow } from "../types";

const TONE = { open: "info", done: "ok", void: "neutral" } as const;

/** Today's and recent bills: open ones to finish, paid ones to look up, and a new bill for products only. */
export default function BillsPage() {
  const { t } = useTranslation("bookings");
  const navigate = useNavigate();
  const { branches, branchId, setBranchId, currency } = useBranch();
  const [status, setStatus] = useState("");
  const [owing, setOwing] = useState(false);
  const [day, setDay] = useState(today());
  const list = useQuery({
    queryKey: ["bookings", "checkouts", branchId, status, owing, day], enabled: !!branchId, refetchInterval: 30_000,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/checkouts", { params: { query: { branch_id: branchId, status: status || undefined, owing: owing || undefined, day: day || undefined } } })),
  });
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/checkouts", { body: { appointment_ids: [], branch_id: branchId, local_id: crypto.randomUUID() } })),
    onSuccess: (co) => navigate(`/checkout/${co.id}`),
  });
  const columns: Column<CheckoutListRow>[] = [
    { header: t("bills.number"), cell: (r) => <span className="font-medium">{r.number}</span>, sortValue: (r) => r.number },
    { header: t("bills.client"), cell: (r) => r.client_name ?? <span className="text-muted">{t("checkout.noClient")}</span>, sortValue: (r) => r.client_name ?? "" },
    { header: t("bills.status"), cell: (r) => <Badge tone={TONE[r.status as keyof typeof TONE] ?? "neutral"}>{t(`checkout.status.${r.status}`, r.status)}</Badge> },
    { header: t("bills.total"), align: "right", cell: (r) => money(r.total, currency), sortValue: (r) => Number(r.total) },
    { header: t("bills.paid"), align: "right", hideBelow: "sm", cell: (r) => money(r.paid_total, currency), sortValue: (r) => Number(r.paid_total) },
    { header: t("bills.when"), hideBelow: "md", cell: (r) => formatDate(r.completed_at ?? r.created_at), sortValue: (r) => r.completed_at ?? r.created_at },
  ];
  return (
    <>
      <PageHeader title={t("bills.title")} description={t("bills.hint")}
        actions={<><BranchPicker branches={branches} value={branchId} onChange={setBranchId} />
          <Button loading={create.isPending} disabled={!branchId} onClick={() => create.mutate()}><Plus className="h-4 w-4" />{t("bills.newBill")}</Button></>} />
      <DataTable rows={list.data} columns={columns} rowKey={(r) => r.id} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()}
        rowHref={(r) => `/checkout/${r.id}`} searchText={(r) => `${r.number} ${r.client_name ?? ""} ${r.invoice_number ?? ""}`} searchPlaceholder={t("bills.search")} pageSize={25}
        empty={{ title: t("bills.empty"), hint: t("bills.emptyHint"), action: <Button onClick={() => create.mutate()} disabled={!branchId}>{t("bills.newBill")}</Button> }}
        toolbar={
          <div className="flex flex-wrap items-center gap-2">
            <Select aria-label={t("bills.status")} className="w-36" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("bills.allStatuses")}</option>
              <option value="open">{t("checkout.status.open")}</option>
              <option value="done">{t("checkout.status.done")}</option>
            </Select>
            <Input type="date" aria-label={t("bills.date")} className="w-40" value={day} onChange={(e) => setDay(e.target.value)} />
            {day && <Button variant="ghost" size="sm" onClick={() => setDay("")}>{t("bills.anyDate")}</Button>}
            <Checkbox label={t("bills.stillOwing")} checked={owing} onChange={(e) => setOwing(e.target.checked)} />
          </div>} />
    </>
  );
}
