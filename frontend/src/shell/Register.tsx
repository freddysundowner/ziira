import { type FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Alert, api, Button, Field, Input, Select, useSession, useTranslation } from "@/sdk";

import { AuthShell } from "./AuthShell";
import { COUNTRIES, countryByCode, CURRENCIES } from "./countries";

type Step = 1 | 2;

/**
 * Registration in two short steps, with no headings: who you are, then your business. The country chosen in step 2 fills in the phone
 * calling code and a default currency (still changeable). An invitation, when the platform asks for one, arrives in the
 * link (?invite=...) rather than a form field.
 */
export function Register() {
  const { t } = useTranslation();
  const { register } = useSession();
  const [params] = useSearchParams();
  const [step, setStep] = useState<Step>(1);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [devToken, setDevToken] = useState<string | null>(null);
  const [person, setPerson] = useState({ owner_name: "", email: "", password: "" });
  const [business, setBusiness] = useState({ business_name: "", country: "", currency: "" });
  const [mode, setMode] = useState<"core" | "standalone">("core");
  const country = countryByCode(business.country);

  const [passwordProblem, setPasswordProblem] = useState<string | null>(null);

  /** Ask the server (the one place that knows the rules) whether the password is acceptable. If it cannot be reached, carry on: sign-up checks again. */
  async function passwordMessage(password: string, email: string): Promise<string | null> {
    try {
      const { data } = await api.POST("/api/v1/auth/password/check", { body: { password, login: email || null } });
      return data && !data.ok ? data.message ?? null : null;
    } catch {
      return null;
    }
  }

  async function next(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const entered = { owner_name: String(form.get("owner_name")), email: String(form.get("email")), password: String(form.get("password")) };
    setPerson(entered);
    setError(null);
    setBusy(true);
    const problem = await passwordMessage(entered.password, entered.email);
    setBusy(false);
    setPasswordProblem(problem);
    if (!problem) setStep(2);
  }

  function chooseCountry(code: string) {
    const chosen = countryByCode(code);
    setBusiness((b) => ({ ...b, country: code, currency: chosen?.currency ?? b.currency }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!country) return;
    setBusy(true);
    const result = await register({
      ...person,
      business_name: business.business_name,
      country: country.code,
      currency: business.currency || country.currency,
      phone_country_code: country.calling,
      timezone: country.zone,
      invite_code: params.get("invite") ?? undefined,
      mode,
    });
    setBusy(false);
    setError(result.error);
    if (!result.error) {
      setSentTo(person.email);
      setDevToken(result.devToken ?? null);
    }
  }

  if (sentTo) {
    return (
      <AuthShell>
        <div className="space-y-3">
          <h1 className="text-2xl font-semibold">{t("register.checkEmail")}</h1>
          <p className="text-sm text-muted">{t("register.sent", { email: sentTo })}</p>
          {devToken && (
            <Alert tone="warn">
              {t("register.devOnly")} <Link className="font-medium underline" to={`/register/verify?token=${encodeURIComponent(devToken)}`}>{t("register.devLink")}</Link>
            </Alert>
          )}
          <Link className="text-sm font-medium text-brand-strong hover:underline" to="/">{t("register.backToSignIn")}</Link>
        </div>
      </AuthShell>
    );
  }

  const shell = "space-y-4";
  return (
    <AuthShell>
      {step === 1 ? (
        <form key="about" onSubmit={next} className={shell}>
          <Field label={t("register.ownerName")}><Input name="owner_name" required minLength={2} maxLength={120} autoComplete="name" defaultValue={person.owner_name} /></Field>
          <Field label={t("register.email")}><Input name="email" type="email" required autoComplete="email" defaultValue={person.email} /></Field>
          <Field label={t("register.password")} error={passwordProblem}>
            <Input name="password" type="password" required minLength={8} autoComplete="new-password" defaultValue={person.password}
              onChange={() => setPasswordProblem(null)}
              onBlur={(e) => { const value = e.target.value; const email = e.target.form?.elements.namedItem("email"); if (value.length >= 8) void passwordMessage(value, email instanceof HTMLInputElement ? email.value : "").then(setPasswordProblem); }} />
          </Field>
          <Button type="submit" size="lg" className="w-full" disabled={busy}>{t("register.next")}</Button>
          <p className="text-center text-sm text-muted"><Link className="font-medium text-brand-strong hover:underline" to="/">{t("register.haveAccount")}</Link></p>
        </form>
      ) : (
        <form key="business" onSubmit={submit} className={shell}>
          <Field label={t("register.businessName")}>
            <Input name="business_name" required minLength={2} maxLength={120} autoComplete="organization" value={business.business_name}
              onChange={(e) => setBusiness((b) => ({ ...b, business_name: e.target.value }))} />
          </Field>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">{t("register.modeLegend")}</legend>
            {(["core", "standalone"] as const).map((m) => (
              <label key={m} className={`flex cursor-pointer gap-3 rounded-xl border p-3 text-sm ${mode === m ? "border-brand bg-brand/5" : "border-line hover:bg-sunken"}`}>
                <input type="radio" name="mode" className="mt-0.5" checked={mode === m} onChange={() => setMode(m)} />
                <span><span className="block font-medium">{t(`register.mode.${m}`)}</span><span className="text-muted">{t(`register.mode.${m}Hint`)}</span></span>
              </label>
            ))}
          </fieldset>
          <Field label={t("register.country")}>
            <Select name="country" required value={business.country} onChange={(e) => chooseCountry(e.target.value)}>
              <option value="" disabled>{t("register.chooseCountry")}</option>
              {COUNTRIES.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
            </Select>
          </Field>
          {country && (
            <>
              <Field label={t("register.currency")}>
                <Select name="currency" value={business.currency} onChange={(e) => setBusiness((b) => ({ ...b, currency: e.target.value }))}>
                  {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              </Field>
              <p className="text-sm text-muted">{t("register.phoneNote", { code: country.calling })}</p>
            </>
          )}
          {error && <Alert tone="bad">{error}</Alert>}
          <div className="flex gap-2">
            <Button type="button" variant="secondary" size="lg" onClick={() => setStep(1)}>{t("register.back")}</Button>
            <Button type="submit" size="lg" loading={busy} disabled={!country} className="flex-1">{busy ? t("register.working") : t("register.submit")}</Button>
          </div>
        </form>
      )}
    </AuthShell>
  );
}
