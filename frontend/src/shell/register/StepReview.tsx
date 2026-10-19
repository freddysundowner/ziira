import type { ReactNode } from "react";

import { Alert, Button, Checkbox, type Edition, useTranslation } from "@/sdk";

import type { Country } from "../countries";
import type { FormApi } from "./form";
import type { StepId } from "./state";

function Section({ title, onEdit, children }: { title: string; onEdit: () => void; children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <section className="rounded-xl border border-line bg-surface p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold">{title}</h3>
        <Button size="sm" variant="ghost" onClick={onEdit} aria-label={`${t("signup.edit")}: ${title}`}>{t("signup.edit")}</Button>
      </div>
      <dl className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-[auto_1fr]">{children}</dl>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation();
  return (
    <>
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 break-words">{value || <span className="text-muted">{t("signup.review.none")}</span>}</dd>
    </>
  );
}

function Link({ href, children }: { href: string; children: string }) {
  return href ? <a className="font-medium text-brand-strong underline" href={href} target="_blank" rel="noopener noreferrer">{children}</a> : <span className="font-medium">{children}</span>;
}

/** Step 5: everything they said, with a way back to each part, and the consent. Never shows the password. */
export function StepReview({ form, edition, country, terms, privacy, onEdit, serverError, industries = [] }: {
  industries?: readonly { id: string; title: string }[];
  form: FormApi; edition: Edition | undefined; country: Country | undefined; terms: string; privacy: string; onEdit: (step: StepId) => void; serverError: string | null;
}) {
  const { t } = useTranslation();
  const { values: v } = form;
  const word = (group: string, key: string) => (key ? t(`signup.${group}.${key}`) : "");
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title={t("signup.review.edition")} onEdit={() => onEdit("need")}>
          <Row label={t("signup.review.edition")} value={edition ? t(`edition.${edition.id}.title`, { defaultValue: edition.title }) : v.edition} />
        </Section>
        <Section title={t("signup.review.you")} onEdit={() => onEdit("about")}>
          <Row label={t("signup.field.name")} value={v.name} />
          <Row label={t("signup.field.email")} value={v.email} />
          <Row label={t("signup.field.phone")} value={v.phone} />
          <Row label={t("signup.field.role")} value={word("role", v.role)} />
        </Section>
        <Section title={t("signup.review.business")} onEdit={() => onEdit("business")}>
          <Row label={t("signup.field.business")} value={v.business} />
          <Row label={t("signup.field.country")} value={country?.name ?? v.country} />
          <Row label={t("signup.field.currency")} value={v.currency} />
          <Row label={t("signup.field.zone")} value={v.zone} />
          <Row label={t("signup.field.tax", { label: country?.taxIdLabel || t("register.taxIdDefault") })} value={v.tax} />
        </Section>
        <Section title={t("signup.review.size")} onEdit={() => onEdit("business")}>
          <Row label={t("signup.field.branches")} value={word("branches", v.branches)} />
          <Row label={t("signup.field.staff")} value={word("staff", v.staff)} />
          <Row label={t("signup.field.kind")} value={industries.find((i) => i.id === v.kind)?.title ?? word("kind", v.kind)} />
        </Section>
      </div>
      <div>
        <Checkbox
          checked={v.consent} onChange={(e) => { form.set("consent", e.target.checked); form.blur("consent"); }} aria-invalid={!!form.error("consent") || undefined}
          label={<span>{t("signup.consent.agree")} <Link href={terms}>{t("signup.consent.terms")}</Link> {t("signup.consent.and")} <Link href={privacy}>{t("signup.consent.privacy")}</Link>.</span>}
        />
        {form.error("consent") && <p role="alert" className="mt-1 text-xs text-bad">{form.error("consent")}</p>}
      </div>
      {serverError && <Alert tone="bad">{serverError}</Alert>}
    </div>
  );
}
