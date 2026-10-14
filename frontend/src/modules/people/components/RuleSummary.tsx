import { money, percent, useTranslation } from "@/sdk";

import { bandRanges, illustrate, type RuleForm, type SideForm } from "../lib/rules";

/** "How this rule works", in plain sentences built only from what the business entered, plus a band table when there are bands. */
export function RuleSummary({ form, currency }: { form: RuleForm; currency?: string }) {
  const { t } = useTranslation("people");
  const m = (v: string) => money(v, currency);
  const side = (who: "employee" | "employer", s: SideForm) => {
    if (s.method === "none") return null;
    const subject = t(`rules.summary.${who}Pays`);
    if (s.method === "fixed") return <li>{t("rules.summary.fixed", { who: subject, amount: m(s.amount || "0") })}</li>;
    if (s.method === "rate") {
      return (
        <li>
          {t("rules.summary.rate", { who: subject, rate: percent(s.rate || "0") })}
          <ul className="ml-4 list-disc text-muted">
            {s.baseMinimum && <li>{t("rules.summary.baseMinimum", { amount: m(s.baseMinimum) })}</li>}
            {s.baseMaximum && <li>{t("rules.summary.baseMaximum", { amount: m(s.baseMaximum) })}</li>}
            {s.minimum && <li>{t("rules.summary.minimum", { amount: m(s.minimum) })}</li>}
            {s.maximum && <li>{t("rules.summary.maximum", { amount: m(s.maximum) })}</li>}
          </ul>
        </li>
      );
    }
    return (
      <li>
        {t("rules.summary.bands", { who: subject })}
        <table className="tnum mt-1.5 w-full max-w-sm text-xs">
          <thead className="text-muted"><tr><th className="py-1 text-left font-medium">{t("rules.bandFrom")}</th><th className="py-1 text-left font-medium">{t("rules.bandTo")}</th><th className="py-1 text-right font-medium">{t("rules.bandRate")}</th></tr></thead>
          <tbody className="divide-y divide-line">
            {bandRanges(s.bands).map((b, i) => (
              <tr key={i}><td className="py-1">{m(b.from)}</td><td className="py-1">{b.to === null ? t("rules.andAbove") : m(b.to)}</td><td className="py-1 text-right">{percent(b.rate)}</td></tr>
            ))}
          </tbody>
        </table>
        {s.credit && Number(s.credit) > 0 && <p className="mt-1 text-muted">{t("rules.summary.credit", { amount: m(s.credit) })}</p>}
      </li>
    );
  };

  return (
    <ul className="space-y-2 text-sm">
      <li>{t("rules.summary.intro", { name: form.name || t("rules.unnamed"), kind: t(`rules.kinds.${form.kind}`), applies: t(`rules.appliesSummary.${form.appliesTo}`), base: t(`rules.baseSummary.${form.base}`) })}</li>
      {side("employee", form.employee)}
      {side("employer", form.employer)}
      {form.reducesTaxable && form.employee.method !== "none" && <li>{t("rules.summary.reduces")}</li>}
      <li className="text-muted">{t("rules.summary.order", { order: form.order || "100" })}</li>
      <li className="text-muted">{t("rules.summary.exempt")}</li>
    </ul>
  );
}

/** A try-it box: what the rule would take from an amount. An illustration for checking a rule against the notice; payroll uses the server's calculation. */
export function RuleTryIt({ form, base, onBase, currency }: { form: RuleForm; base: string; onBase: (v: string) => void; currency?: string }) {
  const { t } = useTranslation("people");
  const amount = Number(base);
  const show = base !== "" && Number.isFinite(amount);
  return (
    <div className="rounded-xl bg-sunken p-4">
      <h4 className="text-sm font-semibold">{t("rules.tryIt")}</h4>
      <p className="mb-2 text-xs text-muted">{t("rules.tryItHint")}</p>
      <div className="flex flex-wrap items-center gap-3">
        <input aria-label={t("rules.tryBase")} inputMode="decimal" placeholder={t("rules.tryBase")} value={base} onChange={(e) => /^\d*\.?\d*$/.test(e.target.value) && onBase(e.target.value)}
          className="tnum h-9 w-40 rounded-lg border border-line bg-surface px-3 text-right text-sm" />
        {show && (
          <p className="text-sm">
            {form.employee.method !== "none" && <span className="mr-4">{t("rules.tryEmployee")}: <b className="tnum">{money(illustrate(form.employee, amount), currency)}</b></span>}
            {form.employer.method !== "none" && <span>{t("rules.tryEmployer")}: <b className="tnum">{money(illustrate(form.employer, amount), currency)}</b></span>}
          </p>
        )}
      </div>
    </div>
  );
}
