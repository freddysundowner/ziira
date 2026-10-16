import { money, useCompany, useTranslation } from "@/sdk";

import { SeverityBadge } from "../components/Badges";
import FactChips from "../components/FactChips";

/** A made-up example of a thing to look at, so the first screen is never empty. Labelled as an example. */
export default function SampleThing() {
  const { t } = useTranslation("intel");
  const { company } = useCompany();
  return (
    <article className="rounded-xl border border-dashed border-line bg-surface p-4">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted"><SeverityBadge severity="medium" /><span>{t("quick.example")}</span></div>
      <h3 className="mt-2 text-base font-semibold">{t("quick.sample.title")}</h3>
      <p className="mt-1 text-sm text-muted">{t("quick.sample.summary")}</p>
      <p className="mt-2 text-sm"><span className="font-medium">{t("card.why")} </span>{t("quick.sample.why")}</p>
      <div className="mt-3"><FactChips facts={[]} currency={company?.currency} lead={[{ label: t("quick.sample.owesLabel"), value: money(24500, company?.currency) }, { label: t("quick.sample.lateLabel"), value: "45" }]} /></div>
    </article>
  );
}
