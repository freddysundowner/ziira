import { type SlotProps, useTranslation } from "@/sdk";

import { useCompanyCounts } from "../api";

/** Receives { productId, companyId } from the Products page. */
export default function CatalogTab(props: SlotProps) {
  const { t } = useTranslation("catalog_stats");
  const count = (useCompanyCounts().data ?? []).find((c) => c.company_id === props.companyId);
  return <p className="text-sm">{t("inCompany")}: <strong>{count?.product_count ?? 0}</strong></p>;
}
