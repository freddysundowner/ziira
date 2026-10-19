import { Check, ShieldCheck, Sparkles } from "lucide-react";
import type { ReactNode } from "react";

import { type Edition, useTranslation } from "@/sdk";

import type { Country } from "../countries";
import type { Values } from "./state";

export interface Trial { plan_name: string; trial_days: number }

function Content({ values, edition, country, trial }: { values: Values; edition: Edition | undefined; country: Country | undefined; trial: Trial | null | undefined }) {
  const { t } = useTranslation();
  const title = edition ? t(`edition.${edition.id}.title`, { defaultValue: edition.title }) : "";
  const steps = (edition?.checklist ?? []).slice(0, 4);
  const line = (label: string, value: string): ReactNode => value ? <p className="text-sm"><span className="text-muted">{label}: </span><span className="font-medium">{value}</span></p> : null;
  return (
    <div className="space-y-6">
      <h2 className="text-base font-semibold">{t("signup.side.title")}</h2>
      {edition && (
        <section aria-label={t("signup.side.chose")} className="space-y-1.5">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t("signup.side.chose")}</p>
          <p className="flex items-center gap-2 text-lg font-semibold"><Sparkles className="h-5 w-5 text-brand" aria-hidden />{title}</p>
          <p className="text-sm text-muted">{t(`edition.${edition.id}.pitch`, { defaultValue: edition.pitch })}</p>
        </section>
      )}
      {trial && <p className="rounded-lg bg-brand-soft px-3 py-2 text-sm font-medium text-brand-strong">{t("signup.side.trial", { days: trial.trial_days, plan: trial.plan_name })}</p>}
      {steps.length > 0 && (
        <section className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">{t("signup.side.firstSteps")}</p>
          <ul className="space-y-1.5 text-sm">
            {steps.map((s) => <li key={s.id} className="flex gap-2"><Check className="mt-0.5 h-4 w-4 shrink-0 text-brand" aria-hidden />{s.title}</li>)}
          </ul>
        </section>
      )}
      {(values.name || values.business || country) && (
        <section className="space-y-1">
          {line(t("signup.side.forYou"), values.name.trim())}
          {line(t("signup.side.business"), values.business.trim())}
          {line(t("signup.side.in"), country?.name ?? "")}
        </section>
      )}
      <section className="space-y-2 rounded-xl bg-sunken p-4">
        <p className="flex items-center gap-2 text-sm font-semibold"><ShieldCheck className="h-4 w-4 text-brand" aria-hidden />{t("signup.side.why")}</p>
        <ul className="space-y-1.5 text-sm text-muted">
          <li>{t("signup.side.r1")}</li>
          <li>{t("signup.side.r2")}</li>
          <li>{t("signup.side.r3")}</li>
        </ul>
      </section>
    </div>
  );
}

/** The right-hand panel: what they chose and what they get. Shown on a very wide screen only (no "Show your setup" fold-away on a phone). */
export function SidePanel(props: { values: Values; edition: Edition | undefined; country: Country | undefined; trial: Trial | null | undefined }) {
  return <div className="hidden 2xl:block"><Content {...props} /></div>;
}
