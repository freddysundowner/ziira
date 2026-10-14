import { Plus } from "lucide-react";
import { useState } from "react";

import { api, Button, Pager, Select, unwrap, usePagedList, useTranslation } from "@/sdk";

import { LeaveRequestDrawer } from "./LeaveRequestDrawer";
import { LeaveTable } from "./LeaveTable";
import type { LeaveType } from "../lib/types";

const STATUSES = ["pending", "approved", "rejected", "cancelled"] as const;

export function RequestsPanel({ companyId, types, names }: { companyId: string; types: LeaveType[]; names: (id: string) => string }) {
  const { t } = useTranslation("people");
  const [status, setStatus] = useState<string>("pending");
  const [asking, setAsking] = useState(false);
  const list = usePagedList(["people", "leave", companyId, status], (limit, offset) =>
    unwrap(api.GET("/api/v1/people/leave-requests", { params: { query: { status: (status || undefined) as "pending" | undefined, limit, offset } } })));

  return (
    <>
      <LeaveTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} types={types} employeeName={names}
        toolbar={<>
          <Select aria-label={t("status")} className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("leave.anyStatus")}</option>{STATUSES.map((s) => <option key={s} value={s}>{t(`state.${s}`)}</option>)}
          </Select>
          <Button className="ml-auto" onClick={() => setAsking(true)}><Plus className="h-4 w-4" />{t("leave.new")}</Button>
        </>}
        empty={{ title: status === "pending" ? t("leave.nonePending") : t("leave.noRequests"), hint: status === "pending" ? t("leave.nonePendingHint") : t("leave.noRequestsHint") }}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <LeaveRequestDrawer open={asking} onClose={() => setAsking(false)} companyId={companyId} />
    </>
  );
}
