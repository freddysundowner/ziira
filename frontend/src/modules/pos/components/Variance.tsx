import { Badge, useTranslation } from "@/sdk";

/** A cash difference: nothing while the till is open, green for none, red for any difference. */
export function Variance({ value, format }: { value: string | null | undefined; format: (v: string) => string }) {
  const { t } = useTranslation("pos");
  if (value === null || value === undefined) return <span className="text-muted">—</span>;
  if (Number(value) === 0) return <Badge tone="ok">{t("balanced")}</Badge>;
  return <span className="font-medium text-bad">{Number(value) > 0 ? "+" : ""}{format(value)}</span>;
}
