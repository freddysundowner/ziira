import { Plus } from "lucide-react";
import { useState } from "react";

import {
  api, Alert, Button, ConfirmDialog, DataTable, Field, formatDate, Input, Menu, Modal, Skeleton, StatusBadge, today, toast, unwrap, useCan, useMutation, useQuery, useQueryClient,
  useTranslation,
} from "@/sdk";

type Period = Awaited<ReturnType<typeof fetchPeriods>>[number];
type Target = "open" | "soft_closed" | "locked";

const fetchPeriods = (companyId: string) => unwrap(api.GET("/api/v1/finance/periods", { params: { query: { company_id: companyId } } }));

/** Monthly periods: open, closed (only people with the close permission post manual entries) and locked (final). Closing runs a checklist first. */
export function PeriodsTab({ companyId }: { companyId: string }) {
  const { t } = useTranslation("finance");
  const qc = useQueryClient();
  const canClose = useCan("period.close");
  const [change, setChange] = useState<{ period: Period; to: Target } | null>(null);
  const [opening, setOpening] = useState(false);
  const periods = useQuery({ enabled: !!companyId, queryKey: ["finance", "periods", companyId], queryFn: () => fetchPeriods(companyId) });
  const refresh = () => qc.invalidateQueries({ queryKey: ["finance", "periods"] });

  const apply = useMutation({
    mutationFn: ({ period, to }: { period: Period; to: Target }) => unwrap(api.POST("/api/v1/finance/periods/{period_id}/status", { params: { path: { period_id: period.id } }, body: { status: to } })),
    onSuccess: (p) => { void refresh(); toast(t(`periods.done.${p.status}`), "ok"); setChange(null); },
    onError: () => setChange(null),
  });

  return (
    <>
      {canClose && <div className="mb-3 flex justify-end"><Button variant="secondary" onClick={() => setOpening(true)}><Plus className="h-4 w-4" />{t("periods.open")}</Button></div>}
      <DataTable
        rows={periods.data} loading={periods.isLoading} error={periods.error?.message} onRetry={() => void periods.refetch()} rowKey={(p) => p.id}
        empty={{ title: t("periods.empty"), hint: t("periods.emptyHint") }}
        columns={[
          { header: t("periods.period"), sortValue: (p) => p.start_date, cell: (p) => <span className="font-medium">{formatDate(p.start_date)} – {formatDate(p.end_date)}</span> },
          { header: t("status"), cell: (p) => <StatusBadge status={p.status} /> },
          { header: t("periods.closedAt"), hideBelow: "md", cell: (p) => (p.closed_at ? formatDate(p.closed_at, true) : "—") },
          {
            header: "", align: "right", cell: (p) => canClose && p.status !== "locked" && (
              <Menu label={t("actions")} trigger={<span className="rounded-lg px-2 py-1 text-muted hover:bg-sunken">•••</span>} items={[
                ...(p.status === "open" ? [{ label: t("periods.close"), onSelect: () => setChange({ period: p, to: "soft_closed" as const }) }] : []),
                ...(p.status === "soft_closed" ? [{ label: t("periods.reopen"), onSelect: () => setChange({ period: p, to: "open" as const }) }] : []),
                { label: t("periods.lock"), danger: true, onSelect: () => setChange({ period: p, to: "locked" as const }) },
              ]} />),
          },
        ]}
      />
      <ChangeDialog change={change} busy={apply.isPending} onClose={() => setChange(null)} onConfirm={() => change && apply.mutate(change)} />
      <OpenPeriod open={opening} onClose={() => setOpening(false)} companyId={companyId} onDone={() => void refresh()} />
    </>
  );
}

function ChangeDialog({ change, busy, onClose, onConfirm }: { change: { period: Period; to: Target } | null; busy: boolean; onClose: () => void; onConfirm: () => void }) {
  const { t } = useTranslation("finance");
  const needsCheck = change?.to === "soft_closed" || change?.to === "locked";
  const checklist = useQuery({
    enabled: !!change && needsCheck, queryKey: ["finance", "checklist", change?.period.id],
    queryFn: () => unwrap(api.GET("/api/v1/finance/periods/{period_id}/checklist", { params: { path: { period_id: change!.period.id } } })),
    gcTime: 0,
  });
  if (!change) return null;
  const blocked = needsCheck && (!checklist.isSuccess || !checklist.data.ready);
  const name = `${formatDate(change.period.start_date)} – ${formatDate(change.period.end_date)}`;
  return (
    <ConfirmDialog open onClose={onClose} busy={busy} danger={change.to === "locked"} title={t(`periods.dialog.${change.to}`)} confirmLabel={t(`periods.dialog.${change.to}`)}
      onConfirm={() => { if (!blocked) onConfirm(); }}
      message={
        <div className="space-y-3">
          <p>{t(`periods.ask.${change.to}`, { period: name })}</p>
          {needsCheck && (checklist.isLoading ? <Skeleton className="h-10 w-full" /> : checklist.error ? <Alert tone="bad">{checklist.error.message}</Alert> : checklist.data?.ready ? (
            <Alert tone="ok">{t("periods.ready")}</Alert>
          ) : (
            <Alert tone="bad"><p className="font-medium">{t("periods.blocked")}</p><ul className="list-disc pl-4">{checklist.data?.problems.map((p) => <li key={p}>{p}</li>)}</ul></Alert>
          ))}
        </div>} />
  );
}

function OpenPeriod({ open, onClose, companyId, onDone }: { open: boolean; onClose: () => void; companyId: string; onDone: () => void }) {
  const { t } = useTranslation("finance");
  const [day, setDay] = useState(today());
  const create = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/finance/periods", { body: { company_id: companyId, day } })),
    onSuccess: () => { onDone(); toast(t("periods.opened"), "ok"); onClose(); },
  });
  return (
    <Modal open={open} onClose={onClose} title={t("periods.open")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button loading={create.isPending} disabled={!day || !companyId} onClick={() => create.mutate()}>{t("periods.open")}</Button></>}>
      <Field label={t("periods.anyDay")} hint={t("periods.openHint")}><Input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field>
    </Modal>
  );
}
