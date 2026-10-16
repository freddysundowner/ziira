import { useEffect } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";

import { api, Alert, formatDate, unwrap, useQuery, useTranslation } from "@/sdk";

import { mustGoToBilling, noticeFor } from "./noticeRules";

/** Above every page, for owners: a trial ending, an ended trial or plan, an overdue payment. A suspended business is sent straight to Plan & billing, the one place it can still act. */
export function BillingNotice() {
  const { t } = useTranslation("kernel");
  const location = useLocation();
  const navigate = useNavigate();
  const status = useQuery({ queryKey: ["billing-status"], queryFn: () => unwrap(api.GET("/api/v1/billing/status")), staleTime: 60_000 });
  const banner = status.data?.banner;
  const goBilling = mustGoToBilling(banner, location.pathname);
  useEffect(() => { if (goBilling) navigate("/admin/billing", { replace: true }); }, [goBilling, navigate]);
  const onBilling = location.pathname.startsWith("/admin/billing");
  const notice = onBilling ? null : noticeFor(banner, (v) => formatDate(v));
  if (!notice) return null;
  return (
    <Alert tone={notice.tone} className="no-print mx-4 mt-3 sm:mx-6 lg:mx-8">
      <p className="font-medium">{notice.text ?? t(notice.key, notice.params)}</p>
      <Link to="/admin/billing" className="mt-1 inline-block font-medium underline">{t("billing.notice.open")}</Link>
    </Alert>
  );
}

/** The address in invoice and reminder emails (`/billing`) leads to Plan & billing, keeping `?attempt=` from a payment provider's return. */
export function BillingLink() {
  const { search } = useLocation();
  return <Navigate to={{ pathname: "/admin/billing", search }} replace />;
}
