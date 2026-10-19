import { Delete, LogOut } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { api, Button, cx, Skeleton, unwrap, useQuery, useTranslation } from "@/sdk";

import { kioskView, type KioskView } from "../gymLogic";
import { useDeskBranch } from "../hooks";
import { isNetworkFailure } from "../offline";
import { checkinPath } from "../public";

const SHOW_SECONDS = 6;
const TERMS_SECONDS = 120;
const KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "-", "0"] as const;

type Step = { kind: "idle" } | { kind: "result"; view: KioskView } | { kind: "terms"; view: KioskView } | { kind: "front-desk"; reasonKey: string };

/** A full-screen check-in that members use themselves: a number or card in, "Welcome" or "Please see the front desk" out. */
export default function KioskPage() {
  const { t } = useTranslation("memberships");
  const { companyId, branchId, field, company } = useDeskBranch("");
  const [text, setText] = useState("");
  const [step, setStep] = useState<Step>({ kind: "idle" });
  const [busy, setBusy] = useState(false);
  const [typedName, setTypedName] = useState("");
  const [agreed, setAgreed] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  const reset = useCallback(() => { setStep({ kind: "idle" }); setText(""); setTypedName(""); setAgreed(false); setProblem(null); window.setTimeout(() => input.current?.focus(), 0); }, []);
  // a result or message clears itself; the terms step waits longer
  useEffect(() => {
    if (step.kind === "idle") return;
    const timer = window.setTimeout(reset, (step.kind === "terms" ? TERMS_SECONDS : SHOW_SECONDS) * 1000);
    return () => window.clearTimeout(timer);
  }, [step, typedName, agreed, reset]);
  useEffect(() => { if (step.kind === "idle") input.current?.focus(); }, [step.kind]);

  const terms = useQuery({
    enabled: step.kind === "terms" && !!companyId, queryKey: ["memberships", "waiver-versions", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/waiver/versions", { params: { query: { company_id: companyId } } })),
  });
  const newest = terms.data?.reduce<(typeof terms.data)[number] | undefined>((a, b) => (!a || b.version > a.version ? b : a), undefined);

  const checkIn = async (body: { identifier?: string; customerId?: string }) => {
    setBusy(true);
    try {
      const res = await unwrap(api.POST("/api/v1/memberships/checkin", { body: {
        company_id: companyId, branch_id: branchId, identifier: body.identifier ?? null, customer_id: body.customerId ?? null, method: "kiosk", device: "kiosk",
        local_id: crypto.randomUUID(), record: true } }));
      const view = kioskView(res);
      setStep(view.outcome === "deny" && view.needsTerms && view.customerId ? { kind: "terms", view } : { kind: "result", view });
    } catch (e) {
      setStep({ kind: "front-desk", reasonKey: isNetworkFailure(e) ? "offline" : "generic" });
    } finally {
      setBusy(false);
      setText("");
    }
  };
  const submit = () => { const value = text.trim(); if (value && !busy && companyId && branchId) void checkIn({ identifier: value }); };

  const accept = async (customerId: string) => {
    setBusy(true);
    setProblem(null);
    try {
      await unwrap(api.POST("/api/v1/memberships/customers/{customer_id}/waiver", {
        params: { path: { customer_id: customerId } }, body: { accepted_name: typedName.trim(), method: "kiosk", version: newest?.version ?? null } }));
      setBusy(false);
      await checkIn({ customerId });
    } catch {
      setBusy(false);
      setStep({ kind: "front-desk", reasonKey: "generic" });
    }
  };

  const shell = "fixed inset-0 z-[100] flex flex-col overflow-y-auto";
  if (!companyId || !branchId) return <div className={cx(shell, "bg-bg p-8")}><Skeleton className="h-40 w-full" /></div>;

  const welcome = step.kind === "result" && step.view.outcome !== "deny";
  const refused = (step.kind === "result" && step.view.outcome === "deny") || step.kind === "front-desk";
  const tone = welcome ? "bg-ok text-ok-ink" : refused ? "bg-bad text-bad-ink" : "bg-bg text-ink";

  return (
    <div className={cx(shell, tone)} data-kiosk>
      <div className="flex items-center justify-between gap-3 p-3 text-sm opacity-80">
        <span className="font-semibold">{company?.name}</span>
        <span className="flex items-center gap-2">
          {step.kind === "idle" && field}
          <Link to={checkinPath} className="inline-flex min-h-9 items-center gap-1 rounded-md px-2 hover:underline"><LogOut className="h-4 w-4" />{t("kiosk.exit")}</Link>
        </span>
      </div>

      <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col items-center justify-center gap-6 px-6 pb-10 text-center">
        {step.kind === "idle" && (
          <>
            <h1 className="text-4xl font-extrabold sm:text-6xl">{t("kiosk.title")}</h1>
            <p className="text-xl text-muted sm:text-2xl">{t("kiosk.prompt")}</p>
            <input ref={input} autoFocus autoComplete="off" autoCorrect="off" spellCheck={false} inputMode="text" aria-label={t("kiosk.inputLabel")}
              value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } }}
              onBlur={() => window.setTimeout(() => input.current?.focus(), 150)}
              className="h-24 w-full rounded-2xl border-4 border-line bg-surface px-6 text-center text-5xl font-bold tracking-wider text-ink focus:border-brand focus:outline-none" />
            <div className="grid w-full max-w-md grid-cols-3 gap-3" role="group" aria-label={t("kiosk.keypad")}>
              {KEYS.map((k) => (
                <button key={k} type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => setText((v) => (v + k).slice(0, 40))}
                  className="h-20 rounded-2xl border border-line bg-surface text-4xl font-bold text-ink shadow-card active:bg-sunken">{k}</button>
              ))}
              <button type="button" onMouseDown={(e) => e.preventDefault()} onClick={() => setText((v) => v.slice(0, -1))} aria-label={t("kiosk.erase")}
                className="flex h-20 items-center justify-center rounded-2xl border border-line bg-surface text-ink shadow-card active:bg-sunken"><Delete className="h-9 w-9" /></button>
            </div>
            <Button size="lg" className="h-20 w-full max-w-md text-3xl" loading={busy} disabled={!text.trim()} onClick={submit}>{t("kiosk.go")}</Button>
          </>
        )}

        {welcome && step.kind === "result" && (
          <>
            <p className="text-6xl font-extrabold sm:text-8xl">{t("kiosk.welcome")}</p>
            {step.view.firstName && <p className="text-4xl font-bold sm:text-6xl">{step.view.firstName}</p>}
            {step.view.reasonKey && <p className="text-2xl sm:text-3xl">{t(`kiosk.reason.${step.view.reasonKey}`)}</p>}
          </>
        )}

        {step.kind === "result" && step.view.outcome === "deny" && (
          <>
            <p className="text-5xl font-extrabold sm:text-7xl">{t("kiosk.seeDesk")}</p>
            {step.view.firstName && <p className="text-3xl font-bold">{step.view.firstName}</p>}
            {step.view.reasonKey && <p className="text-2xl sm:text-3xl">{t(`kiosk.reason.${step.view.reasonKey}`)}</p>}
          </>
        )}

        {step.kind === "front-desk" && (
          <>
            <p className="text-5xl font-extrabold sm:text-7xl">{t("kiosk.seeDesk")}</p>
            <p className="text-2xl sm:text-3xl">{t(`kiosk.reason.${step.reasonKey}`)}</p>
          </>
        )}

        {step.kind === "terms" && (
          <div className="w-full space-y-5 text-left">
            <p className="text-center text-4xl font-extrabold">{step.view.firstName ? t("kiosk.termsTitleName", { name: step.view.firstName }) : t("kiosk.termsTitle")}</p>
            {terms.isLoading && <Skeleton className="h-40 w-full" />}
            {terms.error && <p role="alert" className="text-center text-xl">{t("kiosk.reason.generic")}</p>}
            {newest && (
              <>
                <div className="max-h-[40vh] overflow-y-auto whitespace-pre-wrap rounded-2xl border border-line bg-surface p-5 text-xl text-ink">
                  <p className="mb-2 text-2xl font-bold">{newest.title}</p>{newest.body}
                </div>
                <label className="flex min-h-14 items-center gap-4 text-2xl">
                  <input type="checkbox" className="h-8 w-8" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} />{t("kiosk.agree")}
                </label>
                <label className="block text-xl font-semibold">{t("kiosk.typeName")}
                  <input value={typedName} onChange={(e) => setTypedName(e.target.value)} maxLength={200} autoComplete="off"
                    className="mt-2 h-16 w-full rounded-2xl border-2 border-line bg-surface px-4 text-3xl font-medium text-ink focus:border-brand focus:outline-none" />
                </label>
                {problem && <p role="alert">{problem}</p>}
                <div className="flex gap-3">
                  <Button size="lg" variant="secondary" className="h-16 flex-1 text-xl" onClick={reset}>{t("cancel")}</Button>
                  <Button size="lg" className="h-16 flex-[2] text-2xl" loading={busy} disabled={!agreed || !typedName.trim()} onClick={() => step.view.customerId && void accept(step.view.customerId)}>{t("kiosk.accept")}</Button>
                </div>
              </>)}
          </div>
        )}
      </div>
    </div>
  );
}
