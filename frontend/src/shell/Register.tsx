import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import type { RegisterResult } from "@/sdk/session";
import { Alert, api, Button, formatCountdown, Spinner, unwrap, useCountdown, useEditionChoices, useSession, useTranslation, waitMinutes } from "@/sdk";

import { useCountries } from "./useCountries";
import type { FormApi } from "./register/form";
import { linksFrom, usePublicConfig } from "./register/publicConfig";
import { RegisterLayout } from "./register/RegisterLayout";
import { SignUpClosed } from "./register/SignUpClosed";
import {
  clearDraft, type Context, EMPTY, type FieldKey, firstIncomplete, KINDS, loadDraft, problemsOf, saveDraft, serverProblems, STEPS, type StepId, type Values,
} from "./register/state";
import { type Industry, StepBusiness } from "./register/StepBusiness";
import { StepNeed } from "./register/StepNeed";
import { StepAccount } from "./register/StepAccount";
import { usePasswordCheck } from "./register/usePasswordCheck";

/**
 * Sign-up as a full-page, five-step wizard: what you need, about you, your password, your business, review. Each step
 * validates as the person types (typing mistakes only; the server re-checks on submit and its complaints are shown on
 * the field and step they belong to). Answers survive a refresh in sessionStorage, never the password.
 */
const NO_INDUSTRIES: readonly Industry[] = [];

export function Register() {
  const { t } = useTranslation();
  const { register } = useSession();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const edition = params.get("edition");
  const plan = params.get("plan");
  const choices = useEditionChoices();
  const { countries, byCode } = useCountries();
  const config = usePublicConfig();
  const links = linksFrom(config.data);

  const restored = useRef(loadDraft()).current;
  const [values, setValues] = useState<Values>(restored?.values ?? EMPTY);
  const [step, setStep] = useState<StepId>(restored ? firstEarlier(restored.step, restored.values) : "need");
  const [touched, setTouched] = useState<ReadonlySet<FieldKey>>(new Set());
  const [serverErrors, setServerErrors] = useState<Partial<Record<FieldKey, string>>>({});
  const [attempts, setAttempts] = useState(0);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [blockedUntil, setBlockedUntil] = useState<number | null>(null);
  const timers = useRef<Partial<Record<FieldKey, number>>>({});
  const mainRef = useRef<HTMLElement | null>(null);
  const left = useCountdown(blockedUntil);

  const password = usePasswordCheck(values.password, values.email);
  const country = byCode(values.country);
  const ctx: Context = { taxPattern: country?.taxIdPattern || undefined, passwordOk: password.state === "refused" ? false : password.state === "ok" ? true : null };

  const problems = Object.assign({}, ...STEPS.map((s) => problemsOf(s, values, ctx))) as ReturnType<typeof problemsOf>;
  const stepProblems = problemsOf(step, values, ctx);
  const checking = step === "account" && password.state === "checking";

  // --- the answers --------------------------------------------------------------------------------------------------
  const touch = useCallback((key: FieldKey) => setTouched((s) => (s.has(key) ? s : new Set(s).add(key))), []);
  const set = useCallback(<K extends FieldKey>(key: K, value: Values[K]) => {
    setValues((v) => ({ ...v, [key]: value }));
    setServerErrors((e) => (e[key] ? { ...e, [key]: undefined } : e));
    window.clearTimeout(timers.current[key]);
    timers.current[key] = window.setTimeout(() => touch(key), 500);       // show a mistake shortly after typing stops, not on every key
  }, [touch]);

  const chooseCountry = useCallback((code: string) => {
    const chosen = byCode(code);
    if (!chosen) return;
    setValues((v) => ({ ...v, country: code, currency: chosen.currency, zone: chosen.zone, calling: chosen.calling }));
  }, [byCode]);

  // The form starts on the platform's default country (a Super Admin setting; Kenya to begin with), unless a draft already has one.
  const started = useRef(!!restored?.values.country);
  useEffect(() => {
    if (started.current || countries.length === 0 || config.isLoading) return;
    started.current = true;
    chooseCountry(config.data?.default_country || DEFAULT_COUNTRY);
  }, [countries, chooseCountry, config.isLoading, config.data?.default_country]);

  // ?edition= (or the edition of ?plan=) preselects; unknown values are ignored
  const planList = useQuery({ queryKey: ["public-plans"], enabled: !!plan && !edition, queryFn: () => unwrap(api.GET("/api/v1/public/plans")), staleTime: 60_000 });
  const linked = useRef(false);
  useEffect(() => {
    if (linked.current || !choices.data) return;
    const wanted = edition ?? planList.data?.plans.find((p) => p.code === plan)?.edition ?? null;
    if (plan && !edition && planList.isLoading) return;
    linked.current = true;
    if (wanted && choices.data.some((e) => e.id === wanted)) setValues((v) => ({ ...v, edition: wanted }));
    else if (!choices.data.some((e) => e.id === values.edition)) setValues((v) => ({ ...v, edition: choices.data.find((e) => e.id === "full")?.id ?? choices.data[0]?.id ?? "full" }));
  }, [choices.data, edition, plan, planList.data, planList.isLoading, values.edition]);

  // the kinds of business (industry packs) recommended for the chosen edition: the Services edition asks only these, the shop editions add them to the usual choices
  const asksPacks = ["services", "retail", "distribution"].includes(values.edition);
  const industriesQuery = useQuery({
    queryKey: ["register-industries", values.edition], enabled: asksPacks, staleTime: 60_000, retry: 0,
    queryFn: () => unwrap(api.GET("/api/v1/industries", { params: { query: { edition: values.edition } } })),
  });
  const industries = asksPacks ? (industriesQuery.data ?? NO_INDUSTRIES) : NO_INDUSTRIES;
  useEffect(() => {      // a pack picked for one edition means nothing for another
    const known = (KINDS as readonly string[]).includes(values.kind) || industries.some((i) => i.id === values.kind);
    if (values.kind && !known && (!asksPacks || !industriesQuery.isLoading)) setValues((v) => ({ ...v, kind: "" }));
  }, [values.kind, industries, asksPacks, industriesQuery.isLoading]);

  useEffect(() => saveDraft(values, step), [values, step]);

  // --- moving about -------------------------------------------------------------------------------------------------
  const focusHeading = useCallback(() => window.setTimeout(() => (mainRef.current?.querySelector<HTMLElement>("[data-step-heading]"))?.focus(), 0), []);
  const goTo = useCallback((next: StepId) => { setStep(next); setAttempts(0); setFailure(null); window.scrollTo?.({ top: 0 }); focusHeading(); }, [focusHeading]);

  function showMistakes(fields: FieldKey[]) {
    setTouched((s) => new Set([...s, ...fields]));
    setAttempts((n) => n + 1);
    window.setTimeout(() => mainRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(), 30);
  }

  async function submit() {
    if (busy || left > 0) return;
    const bad = STEPS.find((s) => Object.keys(problemsOf(s, values, ctx)).length > 0);
    if (bad) {
      goTo(bad);
      showMistakes(Object.keys(problemsOf(bad, values, ctx)) as FieldKey[]);
      return;
    }
    setBusy(true);
    setFailure(null);
    let result: RegisterResult;
    try {
      result = await register({
        owner_name: ownerNameFrom(values.email), email: values.email.trim(), password: values.password, business_name: values.business.trim(),
        country: values.country, currency: values.currency.toUpperCase(), phone_country_code: values.calling, timezone: values.zone,
        invite_code: params.get("invite") ?? undefined, edition: values.edition,
        business_type: values.kind || undefined, plan: plan ?? undefined,
      });
    } catch {
      result = { error: t("signup.unavailable") };
    }
    setBusy(false);
    if (!result.error) {
      // The owner goes straight in: the business is created now, the email is only confirmed afterwards (a banner asks).
      const token = result.instantToken ?? result.devToken;
      if (token) {
        clearDraft();
        navigate(`/register/verify?token=${encodeURIComponent(token)}`, { replace: true });
        return;
      }
      setFailure(t("signup.unavailable"));
      return;
    }
    if (result.retryAfter) setBlockedUntil(Date.now() + result.retryAfter * 1000);
    const mapped = serverProblems(result.fields ?? {});
    // a complaint about something this form no longer asks (name, phone ...) has no field to sit under: say it in words
    const asked = new Set<FieldKey>(["edition", "business", "country", "kind", "email", "password", "confirm", "consent"]);
    const unseen = mapped.filter((m) => !asked.has(m.field));
    if (mapped.length > 0 && unseen.length === mapped.length) {
      setFailure(unseen[0].message);
      return;
    }
    if (mapped.length > 0) {
      setServerErrors(Object.fromEntries(mapped.map((m) => [m.field, m.message])));
      setTouched((s) => new Set([...s, ...mapped.map((m) => m.field)]));
      goTo(mapped[0].step);
      setAttempts(1);
      window.setTimeout(() => mainRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(), 30);
      return;
    }
    setFailure(result.status === 429 ? null : result.error);
  }

  function advance() {
    if (step === "account") { void submit(); return; }
    if (Object.keys(stepProblems).length > 0 || checking) {
      showMistakes(Object.keys(stepProblems) as FieldKey[]);
      return;
    }
    goTo(STEPS[STEPS.indexOf(step) + 1]);
  }

  // --- the words for what is wrong ----------------------------------------------------------------------------------
  const form: FormApi = {
    values, set, blur: touch,
    error: (key) => {
      if (serverErrors[key]) return serverErrors[key] ?? null;
      const problem = problems[key];
      if (!problem || !touched.has(key)) return null;
      if (problem.code === "password.refused" && password.message) return password.message;
      return t(`signup.err.${problem.code}`, problem.params);
    },
  };
  const shown = (Object.keys(stepProblems) as FieldKey[]).filter((k) => form.error(k)).length + Object.values(serverErrors).filter(Boolean).length;

  // --- what the rail and the side panel know ------------------------------------------------------------------------
  const done = new Set(STEPS.filter((s) => s === "need" || (s !== "account" && Object.keys(problemsOf(s, values, ctx)).length === 0)));
  const first = firstIncomplete(values, ctx);
  const reachable = new Set(STEPS.filter((s) => STEPS.indexOf(s) <= STEPS.indexOf(first)));

  const mode = config.data?.registration;
  if ((mode === "closed" || (mode === "invite" && !params.get("invite")))) return <SignUpClosed invite={mode === "invite"} support={links.support} />;


  const index = STEPS.indexOf(step);
  const blocked = left > 0;
  const canContinue = Object.keys(stepProblems).length === 0 && !checking && !(blocked && step === "account");
  return (
    <RegisterLayout step={step} done={done} reachable={reachable} onGo={goTo}>
      <div ref={(node) => { mainRef.current = node; }} className="mx-auto w-full max-w-5xl">
        <p className="sr-only" role="status" aria-live="polite">{t("signup.announce", { n: index + 1, total: STEPS.length, title: t(`signup.steps.${step}`) })}</p>
        <form
          noValidate
          onSubmit={(e) => { e.preventDefault(); advance(); }}
          onKeyDown={(e) => {                       // Enter moves on even while Continue is disabled (a disabled button blocks implicit submission)
            const target = e.target as HTMLElement;
            if (e.key === "Enter" && !canContinue && target.tagName === "INPUT" && (target as HTMLInputElement).type !== "radio" && (target as HTMLInputElement).type !== "checkbox") { e.preventDefault(); advance(); }
          }}
          className="space-y-8"
        >
          <header className="space-y-2">
            <h1 tabIndex={-1} data-step-heading className="text-3xl font-semibold outline-none sm:text-4xl">{t(`signup.heading.${step}`)}</h1>
            <p className="max-w-2xl text-base text-muted">{t(`signup.lead.${step}`)}</p>
          </header>

          <div role="alert" aria-live="assertive">
            {attempts > 0 && shown > 0 && <Alert tone="bad">{shown === 1 ? t("signup.summary.needs_one") : t("signup.summary.needs_other", { count: shown })}</Alert>}
          </div>

          {step === "need" && <StepNeed form={form} choices={choices.data} loading={choices.isLoading} failed={!!choices.error} onRetry={() => void choices.refetch()} />}
          {step === "business" && <StepBusiness form={form} countries={countries} country={country} onCountry={chooseCountry} industries={industries} />}
          {step === "account" && (
            <StepAccount form={form} server={password.state} serverMessage={password.message} terms={links.terms} privacy={links.privacy} serverError={failure} />
          )}

          {blocked && <Alert tone="warn">{t("signIn.waitMinutes", { count: waitMinutes(left) })} {t("signIn.countdown", { time: formatCountdown(left) })}</Alert>}

          <div className="flex flex-wrap items-center gap-3 border-t border-line pt-6">
            {index > 0 && <Button variant="secondary" size="lg" onClick={() => goTo(STEPS[index - 1])} disabled={busy}>{t("signup.back")}</Button>}
            <Button type="submit" size="lg" className="min-w-40" disabled={!canContinue || (step === "need" && !choices.data)} loading={busy}>
              {busy ? t("signup.sending") : step === "account" ? t("signup.create") : t("signup.continue")}
            </Button>
            {busy && <span className="flex items-center gap-2 text-sm text-muted" role="status"><Spinner />{t("signup.sendingNote")}</span>}
          </div>
        </form>
      </div>
    </RegisterLayout>
  );
}

/** A restored draft opens where it was, but never past the first step whose answers are missing (the password is never kept). */
/** A first name for the greeting, taken from the email address (the owner can change it in My account). */
/** Used only when the platform cannot say which country the form starts on (it is a Super Admin setting). */
const DEFAULT_COUNTRY = "KE";

export function ownerNameFrom(email: string): string {
  const local = email.trim().split("@")[0] ?? "";
  const word = local.split(/[._+\-\d]+/).find((w) => w.length >= 2) ?? "Owner";     // the server wants at least two letters
  return word.charAt(0).toUpperCase() + word.slice(1, 60);
}

function firstEarlier(saved: StepId, values: Values): StepId {
  const first = firstIncomplete(values, { passwordOk: null });
  return STEPS.indexOf(saved) <= STEPS.indexOf(first) ? saved : first;
}
