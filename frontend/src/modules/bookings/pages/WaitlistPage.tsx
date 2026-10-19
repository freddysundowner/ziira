import { Plus } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, ConfirmDialog, DataTable, Field, formatDate, Input, Modal, PageHeader, Pager, Select, toast, today, unwrap, useCan, useMutation, usePagedList, useTranslation,
} from "@/sdk";

import { BranchPicker } from "../components/BranchBar";
import { type PickedSlot, SlotPicker } from "../components/SlotPicker";
import { WaitlistForm } from "../components/WaitlistForm";
import { useBranch, useOffers, useRefreshBookings } from "../hooks";
import { clock, dayOf } from "../lib";
import type { WaitlistEntry } from "../types";

const TONE = { waiting: "warn", offered: "info", booked: "ok", removed: "neutral" } as const;

export default function WaitlistPage() {
  const { t } = useTranslation("bookings");
  const canManage = useCan("bookings.manage");
  const refresh = useRefreshBookings();
  const { branches, branchId, setBranchId, companyId, zone } = useBranch();
  const offers = useOffers(companyId, false);
  const [status, setStatus] = useState("waiting");
  const [adding, setAdding] = useState(false);
  const [offering, setOffering] = useState<WaitlistEntry | null>(null);
  const [removing, setRemoving] = useState<WaitlistEntry | null>(null);
  const list = usePagedList(["bookings", "waitlist", branchId, status], (limit, offset) =>
    unwrap(api.GET("/api/v1/bookings/waitlist", { params: { query: { branch_id: branchId || undefined, status: status ? [status] : undefined, limit, offset } } })), 25, !!branchId);
  const offerName = (id: string) => offers.data?.find((o) => o.id === id)?.name ?? "—";

  const accept = useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/api/v1/bookings/waitlist/{entry_id}/accept", { params: { path: { entry_id: id } } })),
    onSuccess: () => { void refresh(); toast(t("waitlist.accepted"), "ok"); },
  });
  const remove = useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/api/v1/bookings/waitlist/{entry_id}/remove", { params: { path: { entry_id: id } } })),
    onSuccess: () => { void refresh(); setRemoving(null); },
  });

  return (
    <>
      <PageHeader title={t("waitlist.title")} description={t("waitlist.hint")}
        actions={canManage && <Button onClick={() => setAdding(true)}><Plus className="h-4 w-4" />{t("waitlist.add")}</Button>} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(e) => e.id}
        toolbar={
          <>
            <BranchPicker branches={branches} value={branchId} onChange={setBranchId} />
            <Select className="w-40" aria-label={t("status.label")} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("appointments.allStatuses")}</option>
              {(["waiting", "offered", "booked", "removed"] as const).map((s) => <option key={s} value={s}>{t(`waitlist.statuses.${s}`)}</option>)}
            </Select>
          </>
        }
        empty={{ title: t("waitlist.empty"), hint: t("waitlist.emptyHint") }}
        columns={[
          { header: t("form.name"), cell: (e) => <span className="font-medium">{e.client_name}</span> },
          { header: t("form.service"), hideBelow: "sm", cell: (e) => offerName(e.offer_id) },
          { header: t("waitlist.wanted"), hideBelow: "md", cell: (e) => (e.wanted_from === e.wanted_to ? formatDate(e.wanted_from) : `${formatDate(e.wanted_from)} – ${formatDate(e.wanted_to)}`) },
          { header: t("form.phone"), hideBelow: "lg", cell: (e) => e.client_phone ?? e.client_email ?? "—" },
          { header: t("status.label"), cell: (e) => <Badge tone={TONE[e.status as keyof typeof TONE] ?? "neutral"}>{t(`waitlist.statuses.${e.status}`, e.status)}{e.status === "offered" && e.offered_starts_at ? ` · ${clock(e.offered_starts_at, zone)}` : ""}</Badge> },
          { header: "", cell: (e) => canManage && ["waiting", "offered"].includes(e.status) && (
            <div className="flex justify-end gap-1.5">
              {e.status === "offered" && <Button size="sm" loading={accept.isPending && accept.variables === e.id} onClick={() => accept.mutate(e.id)}>{t("waitlist.accept")}</Button>}
              <Button size="sm" variant="secondary" onClick={() => setOffering(e)}>{t(e.status === "offered" ? "waitlist.offerOther" : "waitlist.offer")}</Button>
              <Button size="sm" variant="ghost" onClick={() => setRemoving(e)}>{t("drawer.remove")}</Button>
            </div>
          ) },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <WaitlistForm open={adding} onClose={() => setAdding(false)} branchId={branchId} companyId={companyId} />
      {offering && <OfferDialog entry={offering} zone={zone} onClose={() => setOffering(null)} />}
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} title={t("waitlist.removeTitle")} message={t("waitlist.removeMessage", { name: removing?.client_name })} danger busy={remove.isPending}
        confirmLabel={t("drawer.remove")} onConfirm={() => removing && remove.mutate(removing.id)} />
    </>
  );
}

/** Pick a free time for a waiting client; they are messaged straight away. */
function OfferDialog({ entry, zone, onClose }: { entry: WaitlistEntry; zone?: string; onClose: () => void }) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const [day, setDay] = useState(entry.wanted_from < today() ? today() : entry.wanted_from);
  const [slot, setSlot] = useState<PickedSlot | null>(null);
  const offer = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/waitlist/{entry_id}/offer", { params: { path: { entry_id: entry.id } }, body: { starts_at: slot?.startIso as string, resource_id: slot?.resourceIds[0] ?? null } })),
    onSuccess: () => { void refresh(); toast(t("waitlist.offered"), "ok"); onClose(); },
  });
  return (
    <Modal open onClose={onClose} title={t("waitlist.offerTitle", { name: entry.client_name })} size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button disabled={!slot} loading={offer.isPending} onClick={() => offer.mutate()}>{t("waitlist.sendOffer")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("form.date")}><Input type="date" value={day} onChange={(e) => { setDay(e.target.value); setSlot(null); }} min={dayOf(new Date(), zone)} /></Field>
        <SlotPicker offerId={entry.offer_id} branchId={entry.branch_id} day={day} resourceId={entry.resource_id ?? undefined} zone={zone} value={slot?.startIso ?? ""} onChange={setSlot} />
        <p className="text-xs text-muted">{t("waitlist.offerHint")}</p>
      </div>
    </Modal>
  );
}
