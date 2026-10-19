import { Bell, CheckCircle2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { Badge, cx, Skeleton, useTranslation } from "@/sdk";

import { bellLabel, bySeverity, SEVERITY_TONE } from "../helpers/alerts";
import { useAlerts } from "./data";

/** The bell: how many things need an operator, and a list of them with a link to where each is dealt with. */
export function AlertsBell() {
  const { t } = useTranslation("operator");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const alerts = useAlerts();

  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const key = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
    };
  }, [open]);

  const total = alerts.data?.total ?? 0;
  const badge = bellLabel(total);
  return (
    <div ref={box} className="relative">
      <button type="button" aria-haspopup="dialog" aria-expanded={open} aria-label={total > 0 ? t("shell.alerts.withCount", { count: total }) : t("shell.alerts.title")} onClick={() => setOpen((o) => !o)}
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-sunken hover:text-ink focus-visible:ring-2 focus-visible:ring-brand">
        <Bell className="h-4 w-4" aria-hidden />
        {badge && <span className={cx("tnum absolute -right-0.5 -top-0.5 min-w-4 rounded-full px-1 text-center text-[10px] font-semibold leading-4 text-bad-ink", alerts.data?.worst === "bad" ? "bg-bad" : "bg-warn")}>{badge}</span>}
      </button>
      {open && (
        <div role="dialog" aria-label={t("shell.alerts.title")} className="absolute right-0 top-11 z-50 w-[22rem] max-w-[calc(100vw-1.5rem)] rounded-xl border border-line bg-surface shadow-pop animate-fade motion-reduce:animate-none">
          <div className="border-b border-line px-4 py-3"><h2 className="text-sm font-semibold">{t("shell.alerts.title")}</h2></div>
          <div className="max-h-[60vh] overflow-y-auto">
            {alerts.isPending ? (
              <div className="space-y-2 p-4"><Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-full" /></div>
            ) : alerts.isError ? (
              <div className="p-4 text-sm"><p className="text-bad">{t("shell.alerts.failed")}</p><button type="button" className="mt-1 font-medium text-brand-strong hover:underline" onClick={() => void alerts.refetch()}>{t("shell.retry")}</button></div>
            ) : alerts.data.items.length === 0 ? (
              <div className="flex items-center gap-2 p-4 text-sm text-muted"><CheckCircle2 className="h-4 w-4 text-ok" aria-hidden /> {t("shell.alerts.none")}</div>
            ) : (
              <ul className="divide-y divide-line">
                {bySeverity(alerts.data.items).map((a) => (
                  <li key={a.key}>
                    <Link to={a.to} onClick={() => setOpen(false)} className="flex items-start gap-3 px-4 py-3 text-sm hover:bg-sunken focus-visible:bg-sunken">
                      <Badge tone={SEVERITY_TONE[a.severity]} className="mt-0.5 shrink-0">{t(`shell.alerts.severity.${a.severity}`)}</Badge>
                      <span className="min-w-0 flex-1">
                        <span className="block font-medium">{t(`shell.alerts.items.${a.key}.title`, { count: a.count })}</span>
                        <span className="block text-xs text-muted">{t(`shell.alerts.items.${a.key}.hint`, { count: a.count })}</span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
