import { useEffect, useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { api, formatDate, unwrap, useQuery, useTranslation } from "@/sdk";

import { NoticeStrip } from "./NoticeStrip";
import { dismissible, mustGoToBilling, noticeFor } from "./noticeRules";

const SEEN_KEY = "ziira.notice.dismissed";
const seen = (): string | null => { try { return sessionStorage.getItem(SEEN_KEY); } catch { return null; } };

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
  const notice = onBilling ? null : noticeFor(banner, (v) => formatDate(v), location.pathname === "/");
  const [hidden, setHidden] = useState(seen);
  if (!notice) return null;
  const id = `${banner?.kind}:${notice.key}`;
  const canHide = dismissible(banner, notice.tone);
  if (canHide && hidden === id) return null;
  return (
    <NoticeStrip tone={notice.tone} to="/admin/billing" action={t("billing.notice.open")}
      onDismiss={canHide ? () => { try { sessionStorage.setItem(SEEN_KEY, id); } catch { /* shown again next time */ } setHidden(id); } : undefined}>
      {notice.text ?? t(notice.key, notice.params)}
    </NoticeStrip>
  );
}

/** The address in invoice and reminder emails (`/billing`) leads to Plan & billing, keeping `?attempt=` from a payment provider's return. */
export function BillingLink() {
  const { search } = useLocation();
  return <Navigate to={{ pathname: "/admin/billing", search }} replace />;
}
