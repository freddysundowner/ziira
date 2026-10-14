import { money, useTranslation } from "@/sdk";

/** The document totals exactly as the server returned them. */
export function Totals({ subtotal, tax, total, currency, extra }: { subtotal: string; tax: string; total: string; currency?: string; extra?: { label: string; value: string; strong?: boolean }[] }) {
  const { t } = useTranslation("purchasing");
  const rows = [{ label: t("subtotal"), value: subtotal }, { label: t("tax"), value: tax }, { label: t("total"), value: total, strong: true }, ...(extra ?? [])];
  return (
    <dl className="ml-auto w-full max-w-xs space-y-1 text-sm">
      {rows.map((r) => (
        <div key={r.label} className={`flex justify-between gap-6 ${r.strong ? "border-t border-line pt-1 font-semibold" : ""}`}>
          <dt className="text-muted">{r.label}</dt>
          <dd className="tnum">{money(r.value, currency)}</dd>
        </div>
      ))}
    </dl>
  );
}
