import { type Fact, formatFact } from "../plainWords";
import { useTranslation } from "@/sdk";

/** A few facts as small labelled chips ("Days late: 45"). */
export default function FactChips({ facts, currency, lead }: { facts: Fact[]; currency: string | undefined; lead?: { label: string; value: string }[] }) {
  const { t } = useTranslation("intel");
  const words = { yes: t("yes"), no: t("no") };
  const items = [...(lead ?? []), ...facts.map((f) => ({ label: f.label, value: formatFact(f.value, f.kind, currency, words) }))];
  if (items.length === 0) return null;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((c) => (
        <li key={c.label} className="rounded-full bg-sunken px-2.5 py-1 text-xs"><span className="text-muted">{c.label}: </span><span className="font-medium text-ink">{c.value}</span></li>
      ))}
    </ul>
  );
}
