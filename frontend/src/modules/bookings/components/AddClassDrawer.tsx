import { useEffect, useState } from "react";

import { api, Alert, Button, Checkbox, Drawer, Field, FormGrid, Input, Select, toast, unwrap, useMutation, useTranslation } from "@/sdk";

import { clampWeeks, wholeOrNull } from "../ops/logic";
import { useOffers, useRefreshBookings } from "../hooks";
import { clock, zonedIso } from "../lib";
import type { Schemas } from "@/sdk";

type Series = Schemas["ClassSessionSeriesOut"];

/** Put a class (or the same class every week) on the timetable. Lists the days that could not be used. */
export function AddClassDrawer({ open, onClose, companyId, branchId, day, zone }: { open: boolean; onClose: () => void; companyId: string; branchId: string; day: string; zone?: string }) {
  const { t } = useTranslation("bookings");
  const offers = useOffers(companyId);
  const refresh = useRefreshBookings();
  const classes = (offers.data ?? []).filter((o) => o.kind === "class");
  const [offer, setOffer] = useState("");
  const [date, setDate] = useState(day);
  const [time, setTime] = useState("09:00");
  const [capacity, setCapacity] = useState("");
  const [repeat, setRepeat] = useState(false);
  const [weeks, setWeeks] = useState("4");
  const [result, setResult] = useState<Series | null>(null);
  useEffect(() => { if (open) { setOffer(""); setDate(day); setTime("09:00"); setCapacity(""); setRepeat(false); setWeeks("4"); setResult(null); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/bookings/sessions", { body: {
      offer_id: offer, starts_at: zonedIso(date, time, zone), branch_id: branchId, capacity: wholeOrNull(capacity), weeks: repeat ? clampWeeks(weeks) : null } })),
    onSuccess: (r) => { void refresh(); setResult(r); toast(t("classes.added", { count: r.created.length }), r.created.length ? "ok" : "warn"); },
  });

  return (
    <Drawer open={open} onClose={onClose} title={t("classes.add")}
      footer={result
        ? <><Button variant="secondary" onClick={() => setResult(null)}>{t("classes.addAnother")}</Button><Button onClick={onClose}>{t("close")}</Button></>
        : <><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button type="submit" form="class-form" loading={save.isPending} disabled={!offer || !date || !time}>{t("classes.add")}</Button></>}>
      {result ? (
        <div className="space-y-3">
          <Alert tone={result.created.length ? "ok" : "warn"}>{t("classes.added", { count: result.created.length })}</Alert>
          {result.skipped.length > 0 && (
            <Alert tone="warn">
              <p className="font-semibold">{t("classes.skipped", { count: result.skipped.length })}</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5">
                {result.skipped.map((s) => <li key={s.starts_at}>{s.starts_at.slice(0, 10)} {clock(s.starts_at, zone)}: {s.problem}</li>)}
              </ul>
            </Alert>
          )}
        </div>
      ) : (
        <form id="class-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Field label={t("classes.which")} required hint={classes.length === 0 && !offers.isLoading ? t("classes.noOffers") : undefined}>
            <Select value={offer} onChange={(e) => setOffer(e.target.value)} autoFocus>
              <option value="">{t("classes.pickClass")}</option>
              {classes.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </Select>
          </Field>
          <FormGrid>
            <Field label={t("form.date")} required><Input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field>
            <Field label={t("form.time")} required><Input type="time" value={time} onChange={(e) => setTime(e.target.value)} /></Field>
          </FormGrid>
          <Field label={t("classes.capacityOptional")} hint={t("classes.capacityHint")}><Input type="number" inputMode="numeric" min={1} max={500} value={capacity} onChange={(e) => setCapacity(e.target.value)} /></Field>
          <Checkbox checked={repeat} onChange={(e) => setRepeat(e.target.checked)} label={t("classes.repeat")} />
          {repeat && <Field label={t("classes.weeks")} hint={t("classes.weeksHint")}><Input type="number" inputMode="numeric" min={1} max={52} value={weeks} onChange={(e) => setWeeks(e.target.value)} /></Field>}
        </form>
      )}
    </Drawer>
  );
}
