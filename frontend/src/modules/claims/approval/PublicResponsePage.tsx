import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { Alert, Button, cx, Field, formatDate, Input, LANGUAGES, money, NumberInput, quantity, readStored, setLanguage, Spinner, Textarea, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import { ResponseError, answerEstimate, loadEstimate } from "./api";
import { EMPTY_PICK, type Pick, openLines, signOffProblems, toBody } from "./answers";

const CHOICES = ["approved", "countered", "rejected", "needs_information"] as const;

/** The page an insurer or other payer opens from the link they were sent: see the estimate with its photos, answer each line, sign off. No sign-in. */
export default function PublicResponsePage() {
  const { token = "" } = useParams();
  const { t, i18n } = useTranslation("claims");
  const qc = useQueryClient();
  const heading = useRef<HTMLHeadingElement>(null);
  const [picks, setPicks] = useState<Record<string, Pick>>({});
  const [who, setWho] = useState({ name: "", role: "", note: "", authority: "", authorityAmount: "" });
  const [tried, setTried] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const page = useQuery({ queryKey: ["claim-response", token], queryFn: () => loadEstimate(token), retry: false, staleTime: 60_000 });
  const send = useMutation({
    meta: { silent: true },
    mutationFn: () => answerEstimate(token, toBody(lines, picks, who)),
    onSuccess: (r) => { setDone(r.response ?? "answered"); void qc.invalidateQueries({ queryKey: ["claim-response", token] }); },
  });
  useEffect(() => {
    if (!readStored("ziira.language") && navigator.language.toLowerCase().startsWith("sw")) setLanguage("sw");
  }, []);
  useEffect(() => { document.title = page.data ? t("response.documentTitle", { business: page.data.business }) : t("response.title"); }, [page.data, t]);
  useEffect(() => { heading.current?.focus(); }, [page.data?.state, done]);

  const e = page.data;
  const lines = e?.lines ?? [];
  const photos = e?.photos ?? [];
  const currency = e?.currency;
  const notFound = page.error instanceof ResponseError && page.error.status === 404;
  const set = (id: string, patch: Partial<Pick>) => setPicks((all) => ({ ...all, [id]: { ...(all[id] ?? EMPTY_PICK), ...patch } }));
  const problems = e ? signOffProblems(lines, picks, who.name) : { lines: {}, name: false };
  const submit = () => {
    if (!e) return;
    setTried(true);
    if (Object.keys(problems.lines).length === 0 && !problems.name) send.mutate();
  };
  return (
    <div className="min-h-screen bg-sunken">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-2xl items-center justify-between gap-3 px-4 py-3">
          <p className="truncate text-sm font-semibold">{e?.business ?? " "}</p>
          <div role="group" aria-label={t("response.language")} className="flex gap-1">
            {(Object.keys(LANGUAGES) as (keyof typeof LANGUAGES)[]).map((l) => (
              <button key={l} type="button" lang={l} aria-pressed={i18n.language === l} onClick={() => setLanguage(l)}
                className={cx("rounded-md px-2 py-1 text-xs font-medium", i18n.language === l ? "bg-brand text-brand-ink" : "text-muted hover:bg-sunken")}>{l.toUpperCase()}</button>
            ))}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-2xl px-4 py-6">
        {page.isLoading && <div className="flex items-center justify-center gap-2 p-16 text-sm text-muted"><Spinner /> {t("response.loading")}</div>}
        {page.error && (
          <div className="rounded-xl border border-line bg-surface p-5 text-center">
            <h1 ref={heading} tabIndex={-1} className="mb-1 text-xl font-semibold outline-none">{notFound ? t("response.notFound") : t("response.failed")}</h1>
            <p className="mb-4 text-sm text-muted">{notFound ? t("response.notFoundHint") : t("response.failedHint")}</p>
            {!notFound && <Button onClick={() => void page.refetch()}>{t("response.retry")}</Button>}
          </div>
        )}
        {e && e.state !== "open" && !done && (
          <div className="rounded-xl border border-line bg-surface p-5 text-center">
            <h1 ref={heading} tabIndex={-1} className="mb-1 text-xl font-semibold outline-none">{t(`response.state.${e.state}`)}</h1>
            <p className="text-sm text-muted">{t(`response.stateHint.${e.state}`, { business: e.business, name: e.answered_by ?? "" })}</p>
          </div>
        )}
        {done && (
          <div className="rounded-xl border border-line bg-surface p-5 text-center">
            <h1 ref={heading} tabIndex={-1} className="mb-1 text-xl font-semibold outline-none">{t("response.thanks")}</h1>
            <p className="text-sm text-muted">{t("response.thanksHint", { business: e?.business ?? "" })}</p>
          </div>
        )}
        {e && e.state === "open" && !done && (
          <>
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">{e.label} · {e.reference}</p>
            <h1 ref={heading} tabIndex={-1} className="mb-3 text-2xl font-semibold outline-none">{t("response.heading", { subject: e.subject ?? e.reference ?? "" })}</h1>
            <dl className="mb-4 grid grid-cols-2 gap-x-4 gap-y-1 rounded-xl border border-line bg-surface p-3 text-sm">
              <dt className="text-muted">{t("response.forPayer")}</dt><dd>{e.payer}</dd>
              {e.claim_number && <><dt className="text-muted">{t("response.claimNumber")}</dt><dd>{e.claim_number}</dd></>}
              {e.policy_number && <><dt className="text-muted">{t("response.policy")}</dt><dd>{e.policy_number}</dd></>}
              {e.loss_date && <><dt className="text-muted">{t("response.loss")}</dt><dd>{formatDate(e.loss_date)}</dd></>}
              {e.valid_until && <><dt className="text-muted">{t("response.validUntil")}</dt><dd>{formatDate(e.valid_until)}</dd></>}
            </dl>
            {e.revision_note && <Alert tone="info" className="mb-4">{e.revision_note}</Alert>}
            {photos.length > 0 && (
              <section aria-label={t("response.photos")} className="mb-4">
                <h2 className="mb-2 text-sm font-semibold">{t("response.photos")}</h2>
                <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                  {photos.map((p) => (
                    <li key={p.id}>
                      <a href={p.original} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-lg border border-line bg-surface">
                        {p.kind === "image" && (p.thumb ?? p.web) ? <img src={p.thumb ?? p.web ?? ""} alt={p.caption || p.name} loading="lazy" className="aspect-square w-full object-cover" /> : <span className="flex aspect-square items-center justify-center p-2 text-center text-xs">{p.name}</span>}
                      </a>
                      {p.caption && <p className="mt-0.5 truncate text-xs text-muted">{p.caption}</p>}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <section aria-label={t("response.lines")} className="space-y-3">
              {lines.map((l) => {
                const pick = picks[l.id] ?? EMPTY_PICK;
                const bad = tried ? problems.lines[l.id] : undefined;
                const open = openLines(lines).some((x) => x.id === l.id);
                return (
                  <article key={l.id} className={cx("rounded-xl border bg-surface p-3 shadow-card", bad ? "border-bad" : "border-line", !open && "opacity-80")}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-medium">{l.description}</p>
                        <p className="tnum text-xs text-muted">{t(`kind.${l.kind}`, { defaultValue: l.kind })}{l.part_class ? ` · ${t(`partClass.${l.part_class}`)}` : ""} · {quantity(l.quantity)} × {money(l.unit_price, currency)}</p>
                      </div>
                      <p className="tnum shrink-0 font-semibold">{money(l.total, currency)}</p>
                    </div>
                    {!open ? (
                      <p className="mt-2 rounded-lg bg-sunken px-3 py-2 text-sm">{l.locked ? t("response.alreadyAgreed", { answer: t(`answer.${l.state}`, { defaultValue: l.state }) }) : t("response.alreadyAnswered", { answer: t(`answer.${l.state}`, { defaultValue: l.state }) })}{l.state === "countered" && l.amount ? ` ${money(l.amount, currency)}` : ""}</p>
                    ) : (
                      <fieldset className="mt-3">
                        <legend className="sr-only">{t("response.yourAnswer", { item: l.description })}</legend>
                        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                          {CHOICES.map((c) => (
                            <button key={c} type="button" aria-pressed={pick.state === c} onClick={() => set(l.id, { state: c })}
                              className={cx("min-h-11 rounded-lg border px-2 py-2 text-sm font-medium", pick.state === c ? "border-brand bg-brand text-brand-ink" : "border-line bg-surface hover:bg-sunken")}>{t(`response.choice.${c}`)}</button>
                          ))}
                        </div>
                        {pick.state === "countered" && (
                          <div className="mt-2"><Field label={t("response.offerAmount")} error={bad === "amount" ? t("response.offerBad", { max: money(l.total, currency) }) : null}>
                            <NumberInput value={pick.amount} inputMode="decimal" invalid={bad === "amount"} className="h-11" onChange={(v) => set(l.id, { amount: v })} />
                          </Field></div>
                        )}
                        {(pick.state === "rejected" || pick.state === "countered" || pick.state === "needs_information") && (
                          <div className="mt-2"><Field label={pick.state === "rejected" ? t("response.reasonRequired") : t("response.reasonOptional")} error={bad === "reason" ? t("response.reasonNeeded") : null}>
                            <Input value={pick.reason} maxLength={500} invalid={bad === "reason"} className="h-11" onChange={(ev) => set(l.id, { reason: ev.target.value })} />
                          </Field></div>
                        )}
                        {bad === "state" && <p role="alert" className="mt-2 text-sm text-bad">{t("response.pickOne")}</p>}
                      </fieldset>
                    )}
                  </article>
                );
              })}
            </section>
            <dl className="mt-3 flex justify-between rounded-xl border border-line bg-surface p-3 text-base font-semibold"><dt>{t("response.total")}</dt><dd className="tnum">{money(e.total, currency)}</dd></dl>
            {e.notes && <p className="mt-3 whitespace-pre-line rounded-xl bg-surface p-3 text-sm text-muted">{e.notes}</p>}
            <form className="mt-5 space-y-3 rounded-xl border border-line bg-surface p-4 shadow-card" onSubmit={(ev) => { ev.preventDefault(); submit(); }}>
              <div className="flex justify-end">
                <Button type="button" size="sm" variant="ghost" onClick={() => setPicks((all) => ({ ...all, ...Object.fromEntries(openLines(lines).filter((l) => !all[l.id]?.state).map((l) => [l.id, { ...EMPTY_PICK, state: "approved" as const }])) }))}>{t("response.approveRest")}</Button>
              </div>
              <Field label={t("response.name")} required error={tried && problems.name ? t("response.nameNeeded") : null}>
                <Input value={who.name} maxLength={160} autoComplete="name" className="h-11" onChange={(ev) => setWho({ ...who, name: ev.target.value })} />
              </Field>
              <Field label={t("response.role")}><Input value={who.role} maxLength={80} autoComplete="organization-title" className="h-11" onChange={(ev) => setWho({ ...who, role: ev.target.value })} /></Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label={t("response.authority")} hint={t("response.authorityHint")}><Input value={who.authority} maxLength={80} className="h-11" onChange={(ev) => setWho({ ...who, authority: ev.target.value })} /></Field>
                <Field label={t("response.authorityAmount")}><NumberInput value={who.authorityAmount} inputMode="decimal" className="h-11" onChange={(v) => setWho({ ...who, authorityAmount: v })} /></Field>
              </div>
              <Field label={t("response.note")}><Textarea value={who.note} maxLength={1000} onChange={(ev) => setWho({ ...who, note: ev.target.value })} /></Field>
              {send.error && <Alert tone="bad">{send.error.message}</Alert>}
              {tried && (Object.keys(problems.lines).length > 0) && <Alert tone="warn">{t("response.fixLines")}</Alert>}
              <Button type="submit" size="lg" loading={send.isPending} className="h-12 w-full">{t("response.signOff")}</Button>
              <p className="text-xs text-muted">{t("response.once")}</p>
            </form>
          </>
        )}
      </main>
    </div>
  );
}
