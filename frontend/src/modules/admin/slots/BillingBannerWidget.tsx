import { Link } from "react-router-dom";

import { api, Alert, unwrap, useQuery, useTranslation } from "@/sdk";

import { bannerTone, STATUS_KEY } from "../pages/billing/lib";

/** Dashboard notice for owners: a trial ending, an overdue invoice, a suspended account. Nothing at all when all is well or the call fails. */
export default function BillingBannerWidget() {
  const { t } = useTranslation("kernel");
  const status = useQuery({ queryKey: STATUS_KEY, queryFn: () => unwrap(api.GET("/api/v1/billing/status")), staleTime: 60_000 });
  const banner = status.data?.banner;
  if (!banner) return null;
  return (
    <Alert tone={bannerTone(banner.level)}>
      <p>{banner.message}</p>
      <Link to="/admin/billing" className="mt-1 inline-block font-medium underline">{t("billing.openBilling")}</Link>
    </Alert>
  );
}
