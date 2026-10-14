import { ShieldAlert } from "lucide-react";

import { api, formatDate, unwrap, useQuery, useTranslation } from "@/sdk";

/** A persistent red bar while Ziira support is working in the business (their own session shows it too). It asks the
 * server once a minute, so it appears and disappears without a reload. */
export function SupportBanner() {
  const { t } = useTranslation();
  const me = useQuery({ queryKey: ["support-banner"], queryFn: () => unwrap(api.GET("/api/v1/auth/me")), refetchInterval: 60_000 });
  const s = me.data?.support_session;
  if (!s) return null;
  return (
    <div role="alert" className="no-print flex flex-wrap items-center justify-center gap-x-3 gap-y-0.5 bg-bad px-3 py-1.5 text-center text-xs font-semibold text-white">
      <ShieldAlert className="h-4 w-4 shrink-0" />
      <span>{t("supportBanner.viewing", { name: s.operator })}</span>
      <span className="font-normal">{t(s.level === "full" ? "supportBanner.full" : "supportBanner.read")} · {t("supportBanner.until", { until: formatDate(s.until, true) })}</span>
    </div>
  );
}
