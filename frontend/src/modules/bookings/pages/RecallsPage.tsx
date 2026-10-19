import { MoreHorizontal } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api, Badge, Button, ConfirmDialog, DataTable, Field, formatDate, Input, Menu, Modal, PageHeader, Select, toast, today, unwrap, useCan, useMutation, useQuery, useTranslation,
} from "@/sdk";

import { BranchPicker } from "../components/BranchBar";
import { useBranch, useRefreshBookings } from "../hooks";
import { addDays } from "../lib";
import { overdueTone } from "../ops/logic";
import type { Schemas } from "@/sdk";

type Recall = Schemas["RecallOut"];
const key = (r: Recall) => `${r.customer_id}:${r.offer_id}`;

/** Clients due for their service again, with what to do about each one. */
export default function RecallsPage() {
  const { t } = useTranslation("bookings");
  const navigate = useNavigate();
  const canManage = useCan("bookings.manage");
  const refresh = useRefreshBookings();
  const { branches, branchId, setBranchId, companyId } = useBranch();
  const [all, setAll] = useState(branches.length > 1 ? "this" : "all");
  const [declining, setDeclining] = useState<Recall | null>(null);
  const [snoozing, setSnoozing] = useState<Recall | null>(null);
  const [until, setUntil] = useState(addDays(today(), 7));

  const scopeBranch = all === "all" ? undefined : branchId || undefined;
  const list = useQuery<Recall[]>({
    queryKey: ["bookings", "recalls", companyId, scopeBranch ?? ""], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/recalls", { params: { query: { company_id: companyId, branch_id: scopeBranch } } })),
  });
  const send = useMutation({
    mutationFn: (r: Recall) => unwrap(api.POST("/api/v1/bookings/recalls/send", { body: { company_id: companyId, customer_id: r.customer_id, offer_id: r.offer_id } })),
    onSuccess: () => { void refresh(); toast(t("recalls.sent"), "ok"); },
  });
  const outcome = useMutation({
    mutationFn: (v: { r: Recall; outcome: "called" | "declined" | "snoozed"; until?: string }) => unwrap(api.POST("/api/v1/bookings/recalls/outcome", {
      body: { company_id: companyId, customer_id: v.r.customer_id, offer_id: v.r.offer_id, outcome: v.outcome, snooze_until: v.until ?? null } })),
    onSuccess: (_d, v) => { void refresh(); setDeclining(null); setSnoozing(null); toast(t(`recalls.done.${v.outcome}`), "ok"); },
  });
  const busy = (r: Recall) => (send.isPending && send.variables && key(send.variables) === key(r)) || (outcome.isPending && outcome.variables && key(outcome.variables.r) === key(r));

  return (
    <>
      <PageHeader title={t("recalls.title")} description={t("recalls.hint")} actions={<BranchPicker branches={branches} value={branchId} onChange={setBranchId} />} />
      <DataTable
        rows={list.data} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={key}
        searchText={(r) => `${r.client_name ?? ""} ${r.client_phone ?? ""} ${r.service}`} searchPlaceholder={t("recalls.search")}
        toolbar={branches.length > 1 && (
          <Select className="w-44" aria-label={t("recalls.scope")} value={all} onChange={(e) => setAll(e.target.value)}>
            <option value="this">{t("recalls.thisBranch")}</option>
            <option value="all">{t("recalls.allBranches")}</option>
          </Select>
        )}
        empty={{ title: t("recalls.empty"), hint: t("recalls.emptyHint") }}
        columns={[
          { header: t("recalls.client"), sortValue: (r) => r.client_name, cell: (r) => (
            <div><p className="font-medium">{r.client_name ?? "—"}</p>{r.client_phone && <p className="text-xs text-muted">{r.client_phone}</p>}</div>
          ) },
          { header: t("recalls.service"), hideBelow: "sm", sortValue: (r) => r.service, cell: (r) => r.service },
          { header: t("recalls.lastVisit"), hideBelow: "lg", sortValue: (r) => r.visited_on, cell: (r) => formatDate(r.visited_on) },
          { header: t("recalls.due"), hideBelow: "md", sortValue: (r) => r.due_on, cell: (r) => formatDate(r.due_on) },
          { header: t("recalls.overdue"), sortValue: (r) => r.overdue_days, cell: (r) => <Badge tone={overdueTone(r.overdue_days)}>{r.overdue_days > 0 ? t("recalls.daysOverdue", { count: r.overdue_days }) : t("recalls.dueNow")}</Badge> },
          { header: t("recalls.contacted"), hideBelow: "lg", cell: (r) => (r.last_contacted_at
            ? <span className="text-sm">{formatDate(r.last_contacted_at)}{r.last_outcome ? ` · ${t(`recalls.outcomes.${r.last_outcome}`, r.last_outcome)}` : ""}</span>
            : <span className="text-muted">{t("recalls.never")}</span>) },
          { header: "", align: "right", cell: (r) => (
            <div className="flex justify-end gap-1.5">
              {canManage && <Button size="sm" loading={!!busy(r) && send.isPending} onClick={() => send.mutate(r)}>{t("recalls.send")}</Button>}
              <Button size="sm" variant="secondary" onClick={() => navigate("/calendar")}>{t("recalls.book")}</Button>
              {canManage && (
                <Menu label={t("recalls.more")} trigger={<span className="flex h-9 w-9 items-center justify-center rounded-lg border border-line"><MoreHorizontal className="h-4 w-4" /></span>} items={[
                  { label: t("recalls.called"), onSelect: () => outcome.mutate({ r, outcome: "called" }) },
                  { label: t("recalls.later"), onSelect: () => { setUntil(addDays(today(), 7)); setSnoozing(r); } },
                  "separator",
                  { label: t("recalls.declined"), danger: true, onSelect: () => setDeclining(r) },
                ]} />
              )}
            </div>
          ) },
        ]}
      />
      <ConfirmDialog open={!!declining} onClose={() => setDeclining(null)} title={t("recalls.declinedTitle")} message={t("recalls.declinedMessage", { name: declining?.client_name ?? "" })} danger busy={outcome.isPending}
        confirmLabel={t("recalls.declined")} onConfirm={() => declining && outcome.mutate({ r: declining, outcome: "declined" })} />
      <Modal open={!!snoozing} onClose={() => setSnoozing(null)} title={t("recalls.laterTitle", { name: snoozing?.client_name ?? "" })}
        footer={<><Button variant="secondary" onClick={() => setSnoozing(null)}>{t("close")}</Button><Button loading={outcome.isPending} disabled={!until} onClick={() => snoozing && outcome.mutate({ r: snoozing, outcome: "snoozed", until })}>{t("recalls.later")}</Button></>}>
        <Field label={t("recalls.remindOn")} hint={t("recalls.remindHint")}><Input type="date" value={until} min={addDays(today(), 1)} onChange={(e) => setUntil(e.target.value)} autoFocus /></Field>
      </Modal>
    </>
  );
}
