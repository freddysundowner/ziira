import { type FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { Alert, Button, Field, Input, Select, useSession, useTranslation } from "@/sdk";

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
  const country = countryByCode(business.country);

  function next(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setPerson({ owner_name: String(form.get("owner_name")), email: String(form.get("email")), password: String(form.get("password")) });
    setError(null);
    setStep(2);
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
      invite_code: params.get("invite") ?? undefined,
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
          <Field label={t("register.password")}><Input name="password" type="password" required minLength={8} autoComplete="new-password" defaultValue={person.password} /></Field>
          <Button type="submit" size="lg" className="w-full">{t("register.next")}</Button>
          <p className="text-center text-sm text-muted"><Link className="font-medium text-brand-strong hover:underline" to="/">{t("register.haveAccount")}</Link></p>
        </form>
      ) : (
        <form key="business" onSubmit={submit} className={shell}>
          <Field label={t("register.businessName")}>
            <Input name="business_name" required minLength={2} maxLength={120} autoComplete="organization" value={business.business_name}
              onChange={(e) => setBusiness((b) => ({ ...b, business_name: e.target.value }))} />
          </Field>
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
