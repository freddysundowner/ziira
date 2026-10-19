import { type FormEvent, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { Alert, Button, Checkbox, cx, Field, Input, LANGUAGES, readStored, setLanguage, Spinner, Textarea, useQuery, useTranslation } from "@/sdk";

import { type PublicBooked, type PublicPage, type PublicSlot, PublicError, loadPage, loadSlots, sendBooking } from "./api";
import { addDay, dayLabel, longLabel, timeLabel, todayIn } from "./dates";

type Step = "service" | "date" | "time" | "details" | "done";
const ORDER: Step[] = ["service", "date", "time", "details"];

/** The page a business shares with its clients: choose a service, a day and a time, leave your details. No sign-in. */
export default function PublicBookingPage() {
  const { slug = "" } = useParams();
  const { t, i18n } = useTranslation("bookings");
  const heading = useRef<HTMLHeadingElement>(null);
  const [step, setStep] = useState<Step>("service");
  const [serviceId, setServiceId] = useState("");
  const [resourceId, setResourceId] = useState("");
  const [day, setDay] = useState("");
  const [slot, setSlot] = useState<PublicSlot | null>(null);
  const [done, setDone] = useState<PublicBooked | null>(null);

  useEffect(() => {          // a visitor whose device speaks Kiswahili and who never chose a language gets it
    if (!readStored("ziira.language") && navigator.language.toLowerCase().startsWith("sw")) setLanguage("sw");
  }, []);
  useEffect(() => { heading.current?.focus(); }, [step]);
  const page = useQuery({ queryKey: ["public-booking", slug], queryFn: () => loadPage(slug), retry: false, staleTime: 60_000 });
  useEffect(() => { document.title = page.data ? t("public.documentTitle", { business: page.data.business }) : t("public.title"); }, [page.data, t]);

  const service = page.data?.services.find((s) => s.id === serviceId);
  const language = i18n.language;
  const stepNumber = ORDER.indexOf(step) + 1;

  return (
    <div className="min-h-screen bg-sunken">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-xl items-center justify-between gap-3 px-4 py-3">
          <p className="truncate text-sm font-semibold">{page.data?.business ?? " "}</p>
          <div role="group" aria-label={t("public.language")} className="flex gap-1">
            {(Object.keys(LANGUAGES) as (keyof typeof LANGUAGES)[]).map((l) => (
              <button key={l} type="button" lang={l} aria-pressed={language === l} onClick={() => setLanguage(l)}
                className={cx("rounded-md px-2 py-1 text-xs font-medium", language === l ? "bg-brand text-brand-ink" : "text-muted hover:bg-sunken")}>{l.toUpperCase()}</button>
            ))}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-xl px-4 py-6">
        {page.isLoading && <div className="flex items-center justify-center gap-2 p-16 text-sm text-muted"><Spinner /> {t("public.loading")}</div>}
        {page.error && <Closed notFound={page.error instanceof PublicError && page.error.status === 404} onRetry={() => void page.refetch()} />}
        {page.data && step !== "done" && (
          <>
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted" aria-live="polite">{t("public.stepOf", { step: stepNumber, total: ORDER.length })}</p>
            <h1 ref={heading} tabIndex={-1} className="mb-1 text-2xl font-semibold outline-none">{t(`public.steps.${step}`)}</h1>
            {page.data.note && step === "service" && <p className="mb-4 text-sm text-muted">{page.data.note}</p>}
            <div className="mt-4 space-y-4 rounded-xl border border-line bg-surface p-4 shadow-card">
              {step === "service" && <ServiceStep page={page.data} onPick={(id) => { setServiceId(id); setResourceId(""); setSlot(null); setStep("date"); }} />}
              {step === "date" && service && (
                <DateStep page={page.data} serviceId={serviceId} resourceId={resourceId} setResourceId={setResourceId} language={language}
                  onPick={(d) => { setDay(d); setSlot(null); setStep("time"); }} />
              )}
              {step === "time" && service && <TimeStep slug={slug} page={page.data} serviceId={serviceId} resourceId={resourceId} day={day} language={language} onPick={(s) => { setSlot(s); setStep("details"); }} />}
              {step === "details" && service && slot && (
                <DetailsStep slug={slug} page={page.data} serviceId={serviceId} serviceName={service.name} resourceId={resourceId} slot={slot} language={language} onDone={(r) => { setDone(r); setStep("done"); }} />
              )}
            </div>
            {step !== "service" && <Button className="mt-4" variant="ghost" onClick={() => setStep(ORDER[ORDER.indexOf(step) - 1] ?? "service")}>← {t("public.back")}</Button>}
          </>
        )}
        {page.data && step === "done" && done && (
          <Done page={page.data} result={done} language={language} onAgain={() => { setDone(null); setSlot(null); setStep("service"); }} />
        )}
      </main>
    </div>
  );
}

function Closed({ notFound, onRetry }: { notFound: boolean; onRetry: () => void }) {
  const { t } = useTranslation("bookings");
  return (
    <div className="rounded-xl border border-line bg-surface p-8 text-center shadow-card" role="alert">
      <h1 className="text-lg font-semibold">{notFound ? t("public.closedTitle") : t("public.errorTitle")}</h1>
      <p className="mt-1 text-sm text-muted">{notFound ? t("public.closedHint") : t("public.errorHint")}</p>
      {!notFound && <Button className="mt-4" variant="secondary" onClick={onRetry}>{t("retry")}</Button>}
    </div>
  );
}

function ServiceStep({ page, onPick }: { page: PublicPage; onPick: (id: string) => void }) {
  const { t } = useTranslation("bookings");
  if (page.services.length === 0) return <p className="text-sm text-muted">{t("public.noServices")}</p>;
  const price = (v: string) => new Intl.NumberFormat(undefined, { style: "currency", currency: page.currency }).format(Number(v));
  return (
    <ul className="space-y-2">
      {page.services.map((s) => (
        <li key={s.id}>
          <button type="button" onClick={() => onPick(s.id)} className="flex w-full items-center justify-between gap-3 rounded-lg border border-line px-4 py-3 text-left hover:border-brand hover:bg-brand-soft/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
            <span className="min-w-0">
              <span className="block font-medium">{s.name}</span>
              <span className="block text-sm text-muted">{t("public.minutes", { count: s.duration_minutes })}{s.description ? ` · ${s.description}` : ""}</span>
            </span>
            {Number(s.price) > 0 && <span className="shrink-0 font-medium tabular-nums">{price(s.price)}</span>}
          </button>
        </li>
      ))}
    </ul>
  );
}

function DateStep({ page, serviceId, resourceId, setResourceId, language, onPick }: { page: PublicPage; serviceId: string; resourceId: string; setResourceId: (id: string) => void; language: string; onPick: (day: string) => void }) {
  const { t } = useTranslation("bookings");
  const today = todayIn(page.timezone);
  const last = addDay(today, page.max_days_ahead);
  const [from, setFrom] = useState(today);
  const service = page.services.find((s) => s.id === serviceId);
  const who = (service?.resource_ids ?? []).map((id) => page.resources.find((r) => r.id === id)).filter((r): r is NonNullable<typeof r> => !!r);
  const days = Array.from({ length: 7 }, (_, i) => addDay(from, i)).filter((d) => d <= last);
  return (
    <div className="space-y-4">
      {who.length > 1 && service?.mode === "any" && (
        <Field label={t("public.with")}>
          <select value={resourceId} onChange={(e) => setResourceId(e.target.value)} className="h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm">
            <option value="">{t("public.anyone")}</option>
            {who.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </Field>
      )}
      <div className="flex items-center justify-between gap-2">
        <Button variant="secondary" size="sm" disabled={from <= today} onClick={() => setFrom(addDay(from, -7) < today ? today : addDay(from, -7))}>← {t("public.earlier")}</Button>
        <Button variant="secondary" size="sm" disabled={addDay(from, 7) > last} onClick={() => setFrom(addDay(from, 7))}>{t("public.later")} →</Button>
      </div>
      <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3" aria-label={t("public.days")}>
        {days.map((d) => (
          <li key={d}><button type="button" onClick={() => onPick(d)} className="h-12 w-full rounded-lg border border-line text-sm font-medium hover:border-brand hover:bg-brand-soft/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">{dayLabel(d, language)}</button></li>
        ))}
      </ul>
      <Field label={t("public.otherDate")}><Input type="date" min={today} max={last} value="" onChange={(e) => e.target.value && onPick(e.target.value)} /></Field>
    </div>
  );
}

function TimeStep({ slug, page, serviceId, resourceId, day, language, onPick }: { slug: string; page: PublicPage; serviceId: string; resourceId: string; day: string; language: string; onPick: (s: PublicSlot) => void }) {
  const { t } = useTranslation("bookings");
  const query = useQuery({ queryKey: ["public-slots", slug, serviceId, day, resourceId], queryFn: () => loadSlots(slug, serviceId, day, resourceId || undefined), retry: false });
  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">{dayLabel(day, language)}</p>
      {query.isLoading && <div className="flex items-center gap-2 text-sm text-muted"><Spinner /> {t("public.loadingTimes")}</div>}
      {query.error && <Alert tone="bad">{query.error instanceof PublicError && query.error.status === 429 ? t("public.slow") : t("public.errorHint")} <button type="button" className="underline" onClick={() => void query.refetch()}>{t("retry")}</button></Alert>}
      {query.data && query.data.length === 0 && <p className="text-sm text-muted">{t("public.noTimes")}</p>}
      <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4" aria-label={t("public.times")}>
        {(query.data ?? []).map((s) => (
          <li key={s.start}><button type="button" onClick={() => onPick(s)} className="h-11 w-full rounded-lg border border-line text-sm font-medium tabular-nums hover:border-brand hover:bg-brand-soft/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">{timeLabel(s.start, page.timezone, language)}</button></li>
        ))}
      </ul>
    </div>
  );
}

function DetailsStep({ slug, page, serviceId, serviceName, resourceId, slot, language, onDone }: {
  slug: string; page: PublicPage; serviceId: string; serviceName: string; resourceId: string; slot: PublicSlot; language: string; onDone: (r: PublicBooked) => void;
}) {
  const { t } = useTranslation("bookings");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [consent, setConsent] = useState(false);
  const [website, setWebsite] = useState("");           // the hidden trap for robots
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const key = useRef<string | null>(null);              // one key per set of details, so a retry cannot book twice
  const edit = <T,>(setter: (v: T) => void) => (v: T) => { key.current = null; setter(v); };
  const ready = name.trim() && (phone.trim() || email.trim()) && consent;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!ready || busy) return;
    key.current ??= crypto.randomUUID();
    setBusy(true); setError("");
    try {
      onDone(await sendBooking(slug, {
        service_id: serviceId, start: slot.start, resource_id: resourceId || undefined, name: name.trim(), phone: phone.trim() || undefined,
        email: email.trim() || undefined, note: note.trim() || undefined, consent, website }, key.current));
    } catch (err) {
      const status = err instanceof PublicError ? err.status : 0;
      setError(status === 429 ? t("public.slow") : status === 0 ? t("public.offline") : (err as Error).message);
    } finally { setBusy(false); }
  };

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-4" noValidate>
      <div className="rounded-lg bg-sunken p-3 text-sm"><p className="font-medium">{serviceName}</p><p className="text-muted">{longLabel(slot.start, page.timezone, language)}</p></div>
      {error && <Alert tone="bad">{error}</Alert>}
      <Field label={t("public.name")} required><Input value={name} onChange={(e) => edit(setName)(e.target.value)} autoComplete="name" maxLength={120} required /></Field>
      <Field label={t("public.phone")} hint={t("public.contactHint")}><Input type="tel" value={phone} onChange={(e) => edit(setPhone)(e.target.value)} autoComplete="tel" maxLength={30} /></Field>
      <Field label={t("public.email")}><Input type="email" value={email} onChange={(e) => edit(setEmail)(e.target.value)} autoComplete="email" maxLength={200} /></Field>
      <Field label={t("public.note")}><Textarea value={note} onChange={(e) => edit(setNote)(e.target.value)} maxLength={300} /></Field>
      <div aria-hidden className="absolute -left-[9999px] h-0 w-0 overflow-hidden"><label>Website<input tabIndex={-1} autoComplete="off" value={website} onChange={(e) => setWebsite(e.target.value)} /></label></div>
      <Checkbox checked={consent} onChange={(e) => edit(setConsent)(e.target.checked)} label={<span className="text-sm">{page.consent_text}</span>} />
      <Button type="submit" size="lg" className="w-full" loading={busy} disabled={!ready}>{t("public.book")}</Button>
    </form>
  );
}

function Done({ page, result, language, onAgain }: { page: PublicPage; result: PublicBooked; language: string; onAgain: () => void }) {
  const { t } = useTranslation("bookings");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  return (
    <div className="rounded-xl border border-line bg-surface p-6 text-center shadow-card" role="status">
      <h1 ref={heading} tabIndex={-1} className="text-2xl font-semibold outline-none">{t(result.status === "confirmed" ? "public.doneConfirmed" : "public.doneRequested")}</h1>
      <p className="mt-3 font-medium">{result.service}</p>
      {result.number && <p className="text-sm text-muted">{longLabel(result.starts_at, page.timezone, language)}</p>}
      <p className="mt-3 text-sm text-muted">{t(result.status === "confirmed" ? "public.doneConfirmedHint" : "public.doneRequestedHint")}</p>
      {result.deposit_due && <p className="mt-3 rounded-lg bg-warn-soft p-3 text-sm text-warn">{t("public.deposit", { amount: result.deposit_due })}{result.deposit_note ? ` ${result.deposit_note}` : ""}</p>}
      {result.number && <p className="mt-2 text-xs text-muted">{t("public.reference", { number: result.number })}</p>}
      <Button className="mt-5" variant="secondary" onClick={onAgain}>{t("public.another")}</Button>
    </div>
  );
}
