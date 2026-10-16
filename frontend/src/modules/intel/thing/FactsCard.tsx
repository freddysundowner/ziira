import { Card, DetailList, formatDate, money, useTranslation } from "@/sdk";
import type { Schemas } from "@/sdk";

import { ageInDays, formatByKind } from "../logic";
import { factsOf, formatFact } from "../plainWords";
import { useNames } from "../useNames";
import { usePlain } from "../usePlain";

type Finding = Schemas["FindingDetailOut"];

/** The facts of one thing in labelled rows: money in the company's currency, counts whole, dates like 13 Oct 2026, people and branches by name. */
export default function FactsCard({ finding: f }: { finding: Finding }) {
  const { t } = useTranslation("intel");
  const plain = usePlain();
  const { branchName, currencyOf } = useNames();
  const currency = currencyOf(f.company_id);
  const words = { yes: t("yes"), no: t("no") };
  const facts = factsOf(f.figures ?? {}, plain.data?.figures ?? {}, 12);
  const period = f.period_start ? `${formatDate(f.period_start)}${f.period_end && f.period_end !== f.period_start ? ` – ${formatDate(f.period_end)}` : ""}` : null;
  const rows: { label: string; value: string }[] = [
    ...(f.amount ? [{ label: t("amount"), value: money(f.amount, currency) }] : []),
    ...(f.value ? [{ label: t("facts.found"), value: formatByKind(f.value, f.value_kind, currency) }] : []),
    ...(f.value && f.expected_value ? [{ label: t("facts.normal"), value: formatByKind(f.expected_value, f.value_kind, currency) }] : []),
    ...facts.map((x) => ({ label: x.label, value: formatFact(x.value, x.kind, currency, words) })),
    ...(branchName(f.branch_id) ? [{ label: t("branch"), value: branchName(f.branch_id)! }] : []),
    ...(period ? [{ label: t("period"), value: period }] : []),
    { label: t("firstSeen"), value: `${formatDate(f.first_seen_at)} (${t("days", { count: ageInDays(f.first_seen_at) })})` },
    ...(f.owner_name ? [{ label: t("assignedTo"), value: f.owner_name }] : []),
    ...(f.resolved_at ? [{ label: t("closedOn"), value: formatDate(f.resolved_at) }] : []),
  ];
  return <Card title={t("facts.title")}><DetailList items={rows} /></Card>;
}
