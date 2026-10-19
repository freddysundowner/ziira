import { Plus } from "lucide-react";
import { useState } from "react";

import { api, Button, DataTable, formatDate, Input, money, PageHeader, Pager, Select, unwrap, useCan, useCurrency, useDebounced, usePagedList, useQuery, useTranslation } from "@/sdk";

import { AppointmentDrawer } from "../components/AppointmentDrawer";
import { BookingForm } from "../components/BookingForm";
import { BranchPicker } from "../components/BranchBar";
import { QuickActions } from "../components/QuickActions";
import { AppointmentStatus } from "../components/StatusBadge";
import { useBranch } from "../hooks";
import { addDays, clock, STATUSES, zonedIso } from "../lib";

export default function AppointmentsPage() {
  const { t } = useTranslation("bookings");
  const canManage = useCan("bookings.manage");
  const { branches, branchId, setBranchId, companyId, zone, currency } = useBranch();
  const [status, setStatus] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const q = useDebounced(search.trim());
  const filtered = !!(status || from || to || q);
  const money_ = useCurrency(companyId) ?? currency;
  const settings = useQuery({
    queryKey: ["bookings", "settings", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/settings", { params: { query: { company_id: companyId } } })),
  });
  const list = usePagedList(["bookings", "appointments", branchId, status, from, to, q, zone], (limit, offset) =>
    unwrap(api.GET("/api/v1/bookings/appointments", { params: { query: {
      branch_id: branchId || undefined, status: status ? [status] : undefined, search: q || undefined, newest_first: !from,
      start: from ? zonedIso(from, "00:00", zone) : undefined, end: to ? zonedIso(addDays(to, 1), "00:00", zone) : undefined, limit, offset } } })),
  25, !!branchId);

  return (
    <>
      <PageHeader title={t("appointments.title")} description={t("appointments.hint")}
        actions={canManage && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("calendar.newAppointment")}</Button>} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
        rowKey={(a) => a.id}
        toolbar={
          <>
            <BranchPicker branches={branches} value={branchId} onChange={setBranchId} />
            <Input className="max-w-xs" aria-label={t("appointments.search")} placeholder={t("appointments.search")} value={search} onChange={(e) => setSearch(e.target.value)} />
            <Select className="w-40" aria-label={t("status.label")} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("appointments.allStatuses")}</option>
              {STATUSES.map((s) => <option key={s} value={s}>{t(`status.${s}`)}</option>)}
            </Select>
            <Input className="w-40" type="date" aria-label={t("appointments.from")} value={from} onChange={(e) => setFrom(e.target.value)} />
            <Input className="w-40" type="date" aria-label={t("appointments.to")} value={to} min={from} onChange={(e) => setTo(e.target.value)} />
          </>
        }
        empty={{ title: filtered ? t("appointments.noMatch") : t("appointments.empty"), hint: filtered ? undefined : t("appointments.emptyHint"),
          action: canManage && !filtered ? <Button onClick={() => setCreating(true)}>{t("calendar.newAppointment")}</Button> : undefined }}
        columns={[
          { header: t("appointments.when"), sortValue: (a) => a.starts_at, cell: (a) => <button type="button" className="text-left font-medium hover:underline" onClick={() => setOpen(a.id)}>{formatDate(a.starts_at)} {clock(a.starts_at, zone)}</button> },
          { header: t("appointments.client"), cell: (a) => a.kind === "class" ? <span className="text-muted">{t("appointments.class", { count: a.attendees })}</span> : a.client_name ?? "—" },
          { header: t("appointments.service"), hideBelow: "sm", cell: (a) => a.service },
          { header: t("appointments.number"), hideBelow: "lg", cell: (a) => <span className="font-mono text-xs">{a.number}</span> },
          { header: t("appointments.price"), hideBelow: "md", align: "right", cell: (a) => money(a.price, money_) },
          { header: t("status.label"), cell: (a) => <AppointmentStatus status={a.status} /> },
          { header: "", cell: (a) => <QuickActions appointment={a} compact invoicing={settings.data?.invoicing_available ?? true} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <AppointmentDrawer appointmentId={open} onClose={() => setOpen(null)} zone={zone} />
      <BookingForm open={creating} onClose={() => setCreating(false)} branchId={branchId} companyId={companyId} zone={zone} onBooked={(id) => setOpen(id)} />
    </>
  );
}
