import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api, Alert, Badge, Button, Card, Drawer, EmptyState, ErrorState, Field, formatDate, FormGrid, IconButton, Input, PageHeader, Select, SkeletonRows, toast, today, unwrap, useCan, useMutation, useQuery, useTranslation, type Schemas,
} from "@/sdk";

import { BranchPicker } from "../components/BranchBar";
import { useBranch, useRefreshBookings } from "../hooks";
import { addDays, weekStart } from "../lib";
import { wholeDays, windowsLabel } from "../ops/logic";

type Person = Schemas["RotaPersonOut"];
const DAYS = [0, 1, 2, 3, 4, 5, 6];

/** Who works when this week, and who is away. Hours are edited under Staff and rooms. */
export default function RotaPage() {
  const { t } = useTranslation("bookings");
  const navigate = useNavigate();
  const canSetup = useCan("bookings.setup");
  const { branches, branchId, setBranchId, zone } = useBranch();
  const [day, setDay] = useState(today());
  const [adding, setAdding] = useState(false);
  const first = weekStart(day);
  const rota = useQuery<Person[]>({
    queryKey: ["bookings", "rota", branchId, first], enabled: !!branchId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/rota", { params: { query: { branch_id: branchId, week_start: first } } })),
  });
  const edit = () => navigate("/booking/resources");
  const windows = (p: Person, d: number) => windowsLabel(p.days.find((x) => x.weekday === d)?.windows ?? []);

  return (
    <>
      <PageHeader title={t("rota.title")} description={t("rota.hint")}
        actions={<><BranchPicker branches={branches} value={branchId} onChange={setBranchId} />{canSetup && <Button onClick={() => setAdding(true)}><Plus className="h-4 w-4" />{t("rota.addOff")}</Button>}</>} />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <IconButton label={t("classes.prevWeek")} onClick={() => setDay(addDays(first, -7))}><ChevronLeft className="h-4 w-4" /></IconButton>
        <p className="min-w-0 flex-1 text-center text-sm font-semibold sm:flex-none sm:px-3">{formatDate(first)} – {formatDate(addDays(first, 6))}</p>
        <IconButton label={t("classes.nextWeek")} onClick={() => setDay(addDays(first, 7))}><ChevronRight className="h-4 w-4" /></IconButton>
        <Button variant="secondary" size="sm" onClick={() => setDay(today())}>{t("classes.thisWeek")}</Button>
      </div>

      {rota.isLoading && <Card><SkeletonRows rows={5} cols={6} /></Card>}
      {rota.error && <Card><ErrorState message={rota.error.message} onRetry={() => void rota.refetch()} /></Card>}
      {rota.data && rota.data.length === 0 && (
        <Card><EmptyState title={t("rota.empty")} hint={t("rota.emptyHint")} action={<Button onClick={edit}>{t("rota.openStaff")}</Button>} /></Card>
      )}

      {rota.data && rota.data.length > 0 && (
        <>
          <Card flush className="hidden md:block">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-left">
                    <th scope="col" className="px-4 py-3 eyebrow">{t("staffPay.person")}</th>
                    {DAYS.map((d) => <th key={d} scope="col" className="px-2 py-3 eyebrow">{t(`weekdaysShort.${d}`)} <span className="font-normal normal-case text-muted">{addDays(first, d).slice(8)}</span></th>)}
                  </tr>
                </thead>
                <tbody>
                  {rota.data.map((p) => (
                    <tr key={p.resource_id} className="border-b border-line align-top last:border-b-0">
                      <th scope="row" className="px-4 py-3 text-left font-normal">
                        <button type="button" onClick={edit} className="text-left font-medium hover:underline">{p.name}</button>
                        {p.level && <p className="text-xs text-muted">{p.level}</p>}
                        {p.time_off.length > 0 && <div className="mt-1.5 flex flex-wrap gap-1">{p.time_off.map((o) => <Badge key={o} tone="warn" className="whitespace-normal">{t("rota.off")}: {o}</Badge>)}</div>}
                      </th>
                      {DAYS.map((d) => (
                        <td key={d} className="px-2 py-3">
                          {windows(p, d) ? <span className="tnum rounded-md bg-ok-soft px-1.5 py-1 text-xs font-medium text-ok">{windows(p, d)}</span> : <span className="text-muted">—</span>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <ul className="space-y-3 md:hidden">
            {rota.data.map((p) => (
              <li key={p.resource_id}>
                <Card>
                  <button type="button" onClick={edit} className="mb-2 flex min-h-[44px] w-full items-center justify-between text-left">
                    <span><span className="font-semibold">{p.name}</span>{p.level && <span className="ml-2 text-xs text-muted">{p.level}</span>}</span>
                    <span className="text-xs font-semibold text-brand-strong">{t("rota.editHours")}</span>
                  </button>
                  <dl className="grid grid-cols-[3rem_1fr] gap-x-3 gap-y-1.5 text-sm">
                    {DAYS.map((d) => (
                      <div key={d} className="contents">
                        <dt className="text-muted">{t(`weekdaysShort.${d}`)}</dt>
                        <dd className="tnum">{windows(p, d) || <span className="text-muted">{t("rota.dayOff")}</span>}</dd>
                      </div>
                    ))}
                  </dl>
                  {p.time_off.length > 0 && <div className="mt-3 flex flex-wrap gap-1">{p.time_off.map((o) => <Badge key={o} tone="warn" className="whitespace-normal">{t("rota.off")}: {o}</Badge>)}</div>}
                </Card>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted">{t("rota.editNote")}</p>
        </>
      )}

      <TimeOffDrawer open={adding} onClose={() => setAdding(false)} people={rota.data ?? []} zone={zone} day={day} />
    </>
  );
}

function TimeOffDrawer({ open, onClose, people, zone, day }: { open: boolean; onClose: () => void; people: Person[]; zone?: string; day: string }) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const [who, setWho] = useState("");
  const [from, setFrom] = useState(day);
  const [to, setTo] = useState(day);
  const [reason, setReason] = useState("");
  const [affected, setAffected] = useState<number | null>(null);
  useEffect(() => { if (open) { setWho(""); setFrom(day); setTo(day); setReason(""); setAffected(null); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: () => {
      const r = wholeDays(from, to, zone);
      return unwrap(api.POST("/api/v1/bookings/resources/{resource_id}/time-off", { params: { path: { resource_id: who } }, body: { starts_at: r.startsAt, ends_at: r.endsAt, reason: reason.trim() || null } }));
    },
    onSuccess: (r) => { void refresh(); setAffected(r.affected_appointments); toast(t("rota.offSaved"), "ok"); },
  });

  return (
    <Drawer open={open} onClose={onClose} title={t("rota.addOff")}
      footer={affected !== null
        ? <Button onClick={onClose}>{t("close")}</Button>
        : <><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button type="submit" form="timeoff-form" loading={save.isPending} disabled={!who || !from || !to}>{t("save")}</Button></>}>
      {affected !== null ? (
        <Alert tone={affected > 0 ? "warn" : "ok"}>{affected > 0 ? t("rota.affected", { count: affected }) : t("rota.noneAffected")}</Alert>
      ) : (
        <form id="timeoff-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Field label={t("staffPay.person")} required>
            <Select value={who} onChange={(e) => setWho(e.target.value)} autoFocus>
              <option value="">{t("rota.pickPerson")}</option>
              {people.map((p) => <option key={p.resource_id} value={p.resource_id}>{p.name}</option>)}
            </Select>
          </Field>
          <FormGrid>
            <Field label={t("staffPay.from")} required><Input type="date" value={from} onChange={(e) => { setFrom(e.target.value); if (to < e.target.value) setTo(e.target.value); }} /></Field>
            <Field label={t("staffPay.to")} required hint={t("rota.toHint")}><Input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></Field>
          </FormGrid>
          <Field label={t("rota.reason")}><Input value={reason} maxLength={200} onChange={(e) => setReason(e.target.value)} /></Field>
        </form>
      )}
    </Drawer>
  );
}
