import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { Alert, Button, cx, Field, formatDate, Input, LANGUAGES, money, readStored, setLanguage, Spinner, Textarea, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import { answerEstimate, ApprovalError, loadEstimate } from "./api";

/** The page a customer opens from the link they were sent: see the estimate, approve or decline. No sign-in. */
export default function PublicApprovalPage() {
  const { token = "" } = useParams();
  const { t, i18n } = useTranslation("jobs");
  const qc = useQueryClient();
  const heading = useRef<HTMLHeadingElement>(null);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [asked, setAsked] = useState(false);
  const page = useQuery({ queryKey: ["job-approval", token], queryFn: () => loadEstimate(token), retry: false, staleTime: 30_000 });
  const answer = useMutation({
    meta: { silent: true },
    mutationFn: (approve: boolean) => answerEstimate(token, { approve, name: name.trim(), note: note.trim() || undefined }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job-approval", token] }),
  });
  useEffect(() => {
    if (!readStored("ziira.language") && navigator.language.toLowerCase().startsWith("sw")) setLanguage("sw");
  }, []);
  useEffect(() => { document.title = page.data ? t("approval.documentTitle", { business: page.data.business }) : t("approval.title"); }, [page.data, t]);
  useEffect(() => { heading.current?.focus(); }, [page.data?.state]);

  const e = page.data;
  const currency = e?.currency;
  const submit = (approve: boolean) => { setAsked(true); if (name.trim()) answer.mutate(approve); };
  return (
    <div className="min-h-screen bg-sunken">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-xl items-center justify-between gap-3 px-4 py-3">
          <p className="truncate text-sm font-semibold">{e?.business ?? " "}</p>
          <div role="group" aria-label={t("approval.language")} className="flex gap-1">
            {(Object.keys(LANGUAGES) as (keyof typeof LANGUAGES)[]).map((l) => (
              <button key={l} type="button" lang={l} aria-pressed={i18n.language === l} onClick={() => setLanguage(l)}
                className={cx("rounded-md px-2 py-1 text-xs font-medium", i18n.language === l ? "bg-brand text-brand-ink" : "text-muted hover:bg-sunken")}>{l.toUpperCase()}</button>
            ))}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-xl px-4 py-6">
        {page.isLoading && <div className="flex items-center justify-center gap-2 p-16 text-sm text-muted"><Spinner /> {t("approval.loading")}</div>}
        {page.error && (
          <div className="rounded-xl border border-line bg-surface p-5 text-center">
            <h1 ref={heading} tabIndex={-1} className="mb-1 text-xl font-semibold outline-none">{page.error instanceof ApprovalError && page.error.status === 404 ? t("approval.notFound") : t("approval.failed")}</h1>
            <p className="mb-4 text-sm text-muted">{page.error instanceof ApprovalError && page.error.status === 404 ? t("approval.notFoundHint") : t("approval.failedHint")}</p>
            {!(page.error instanceof ApprovalError && page.error.status === 404) && <Button onClick={() => void page.refetch()}>{t("approval.retry")}</Button>}
          </div>
        )}
        {e && (
          <>
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">{e.job_number} · {e.item}</p>
            <h1 ref={heading} tabIndex={-1} className="mb-3 text-2xl font-semibold outline-none">{t("approval.heading", { title: e.title })}</h1>
            {e.kind === "additional" && <Alert tone="info" className="mb-3">{t("garage.approval.additional")}</Alert>}
            {e.photos.length > 0 && (
              <section aria-label={t("garage.approval.photos")} className="mb-3 grid grid-cols-3 gap-2">
                {e.photos.filter((p) => p.kind === "image").map((p) => (
                  <a key={p.id} href={p.web_path ?? p.original_path} target="_blank" rel="noreferrer" className="block overflow-hidden rounded-lg border border-line bg-surface">
                    <img src={p.thumb_path ?? p.web_path ?? p.original_path} alt={p.caption || p.category} loading="lazy" className="aspect-square w-full object-cover" />
                  </a>
                ))}
              </section>
            )}
            <section aria-label={t("approval.lines")} className="rounded-xl border border-line bg-surface shadow-card">
              <ul className="divide-y divide-line">
                {e.lines.map((l, i) => (
                  <li key={i} className="flex items-start justify-between gap-3 p-3 text-sm">
                    <span className="min-w-0"><span className="block font-medium">{l.description}{l.part_class && <span className="ml-2 rounded bg-sunken px-1.5 py-0.5 text-xs font-normal text-muted">{t(`garage.parts.classes.${l.part_class}`)}</span>}</span><span className="tnum text-xs text-muted">{Number(l.quantity)} × {money(l.unit_price, currency)}</span></span>
                    <span className="tnum shrink-0 font-medium">{money(l.total, currency)}</span>
                  </li>
                ))}
              </ul>
              <dl className="space-y-1 border-t border-line p-3 text-sm">
                <div className="flex justify-between text-muted"><dt>{t("approval.tax")}</dt><dd className="tnum">{money(e.tax, currency)}</dd></div>
                <div className="flex justify-between text-base font-semibold"><dt>{t("approval.total")}</dt><dd className="tnum">{money(e.total, currency)}</dd></div>
              </dl>
            </section>
            {e.notes && <p className="mt-3 whitespace-pre-line rounded-xl bg-surface p-3 text-sm text-muted">{e.notes}</p>}
            {e.valid_until && e.state === "open" && <p className="mt-2 text-xs text-muted">{t("approval.validUntil", { date: formatDate(e.valid_until) })}</p>}
            <div className="mt-5" aria-live="polite">
              {e.state === "open" ? (
                <form className="space-y-3 rounded-xl border border-line bg-surface p-4 shadow-card" onSubmit={(ev) => { ev.preventDefault(); submit(true); }}>
                  <Field label={t("approval.name")} required error={asked && !name.trim() ? t("approval.nameNeeded") : null}>
                    <Input value={name} maxLength={160} autoComplete="name" onChange={(x) => setName(x.target.value)} className="h-11" />
                  </Field>
                  <Field label={t("approval.note")}><Textarea value={note} maxLength={1000} onChange={(x) => setNote(x.target.value)} /></Field>
                  {answer.error && <Alert tone="bad">{answer.error.message}</Alert>}
                  <div className="grid grid-cols-2 gap-2">
                    <Button type="submit" size="lg" loading={answer.isPending} className="h-12">{t("approval.approve")}</Button>
                    <Button type="button" size="lg" variant="secondary" disabled={answer.isPending} className="h-12" onClick={() => submit(false)}>{t("approval.decline")}</Button>
                  </div>
                  <p className="text-xs text-muted">{t("approval.once")}</p>
                </form>
              ) : (
                <Alert tone={e.state === "approved" ? "ok" : e.state === "declined" ? "info" : "warn"}>{t(`approval.state.${e.state}`)}</Alert>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
