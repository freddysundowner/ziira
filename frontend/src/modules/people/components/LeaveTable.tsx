import { type ReactNode, useState } from "react";

import {
  api, Button, ConfirmDialog, DataTable, Field, formatDate, Input, Modal, quantity, StatusBadge, toast, today, unwrap, useCan, useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import type { Leave, LeaveType } from "../lib/types";

/** Leave requests with the actions the user may take: approve or reject (with a note) and cancel. */
export function LeaveTable({ rows, loading, error, onRetry, employeeName, types, toolbar, footer, empty }: {
  rows: readonly Leave[] | undefined; loading: boolean; error?: string; onRetry: () => void; employeeName?: (id: string) => string; types: LeaveType[];
  toolbar?: ReactNode; footer?: ReactNode; empty: { title: string; hint?: string };
}) {
  const { t } = useTranslation("people");
  const qc = useQueryClient();
  const canDecide = useCan("leave.approve");
  const [deciding, setDeciding] = useState<{ leave: Leave; approve: boolean } | null>(null);
  const [cancelling, setCancelling] = useState<Leave | null>(null);
  const [note, setNote] = useState("");
  const refresh = () => void qc.invalidateQueries({ queryKey: ["people"] });

  const decide = useMutation({
    mutationFn: ({ leave, approve }: { leave: Leave; approve: boolean }) => unwrap(api.POST(approve ? "/api/v1/people/leave-requests/{leave_id}/approve" : "/api/v1/people/leave-requests/{leave_id}/reject", { params: { path: { leave_id: leave.id } }, body: { note: note.trim() || null } })),
    onSuccess: (_, v) => { refresh(); toast(t(v.approve ? "leave.approvedDone" : "leave.rejectedDone"), "ok"); setDeciding(null); setNote(""); },
  });
  const cancel = useMutation({
    mutationFn: (leave: Leave) => unwrap(api.POST("/api/v1/people/leave-requests/{leave_id}/cancel", { params: { path: { leave_id: leave.id } } })),
    onSuccess: () => { refresh(); toast(t("leave.cancelledDone"), "ok"); setCancelling(null); },
  });
  const typeName = (id: string) => types.find((x) => x.id === id)?.name ?? "—";

  return (
    <>
      <DataTable
        rows={rows} loading={loading} error={error} onRetry={onRetry} rowKey={(l) => l.id} empty={empty} toolbar={toolbar} footer={footer}
        columns={[
          ...(employeeName ? [{ header: t("leave.employee"), sortValue: (l: Leave) => employeeName(l.employee_id), cell: (l: Leave) => <span className="font-medium">{employeeName(l.employee_id)}</span> }] : []),
          { header: t("leave.type"), hideBelow: "sm" as const, cell: (l: Leave) => typeName(l.leave_type_id) },
          { header: t("leave.period"), sortValue: (l: Leave) => l.start_date, cell: (l: Leave) => <span>{formatDate(l.start_date)}{l.end_date !== l.start_date && ` → ${formatDate(l.end_date)}`}{l.reason && <span className="block max-w-xs truncate text-xs text-muted">{l.reason}</span>}</span> },
          { header: t("leave.days"), align: "right" as const, cell: (l: Leave) => quantity(l.days) },
          { header: t("status"), cell: (l: Leave) => <StatusBadge status={l.status} /> },
          {
            header: "", align: "right" as const, cell: (l: Leave) => (
              <span className="flex justify-end gap-1.5">
                {canDecide && l.status === "pending" && <><Button size="sm" onClick={() => setDeciding({ leave: l, approve: true })}>{t("approve")}</Button><Button size="sm" variant="secondary" onClick={() => setDeciding({ leave: l, approve: false })}>{t("reject")}</Button></>}
                {(l.status === "pending" || (l.status === "approved" && l.start_date >= today())) && <Button size="sm" variant="ghost" onClick={() => setCancelling(l)}>{t("leave.cancel")}</Button>}
              </span>
            ),
          },
        ]}
      />
      <Modal open={!!deciding} onClose={() => { setDeciding(null); setNote(""); }} size="sm" title={deciding?.approve ? t("leave.approve") : t("leave.reject")}
        footer={<><Button variant="secondary" onClick={() => setDeciding(null)}>{t("cancel")}</Button><Button variant={deciding?.approve ? "primary" : "danger"} loading={decide.isPending} onClick={() => deciding && decide.mutate(deciding)}>{deciding?.approve ? t("approve") : t("reject")}</Button></>}>
        {deciding && <p className="mb-3 text-sm text-muted">{t("leave.decideAsk", { name: employeeName?.(deciding.leave.employee_id) ?? "", from: formatDate(deciding.leave.start_date), to: formatDate(deciding.leave.end_date), days: quantity(deciding.leave.days) })}</p>}
        <Field label={t("leave.note")} hint={t("leave.noteHint")}><Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} /></Field>
      </Modal>
      <ConfirmDialog open={!!cancelling} onClose={() => setCancelling(null)} busy={cancel.isPending} danger title={t("leave.cancel")} confirmLabel={t("leave.cancel")}
        message={t("leave.cancelAsk")} onConfirm={() => cancelling && cancel.mutate(cancelling)} />
    </>
  );
}
