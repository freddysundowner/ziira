import { useTranslation } from "@/sdk";

import { useCompanyCounts } from "../api";

export default function ProductCountWidget() {
  const { t } = useTranslation("catalog_stats");
  const counts = useCompanyCounts().data ?? [];
  if (counts.length === 0) return <p className="text-sm text-muted">{t("none")}</p>;
  return (
    <ul className="space-y-1 text-sm">
      {counts.map((c) => (
        <li key={c.company_id}><span className="text-2xl font-semibold">{c.product_count}</span> {t("products")}</li>
      ))}
    </ul>
  );
}
