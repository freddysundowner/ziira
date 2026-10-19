import { CircleAlert, Info, X } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { cx, useTranslation } from "@/sdk";

const TONES = { info: "bg-info-soft text-info", warn: "bg-warn-soft text-warn", bad: "bg-bad-soft text-bad" } as const;

/**
 * A slim notice about the account at the very top of a page (a trial ending, a payment overdue): one line, an icon, the message and one
 * link. Not a card. `onDismiss` is given only where hiding it is safe.
 */
export function NoticeStrip({ tone, children, to, action, onDismiss }: { tone: keyof typeof TONES; children: ReactNode; to: string; action: string; onDismiss?: () => void }) {
  const { t } = useTranslation();
  const Icon = tone === "info" ? Info : CircleAlert;
  return (
    <div role={tone === "bad" ? "alert" : "status"} data-notice className={cx("no-print flex items-center gap-x-3 gap-y-1 px-3 py-1.5 text-sm sm:px-5", TONES[tone])}>
      <Icon className="h-4 w-4 shrink-0" aria-hidden />
      <p className="min-w-0 flex-1 font-medium sm:flex-initial sm:truncate">{children}</p>
      <Link to={to} className="shrink-0 whitespace-nowrap font-semibold underline underline-offset-2">{action}</Link>
      <span className="hidden flex-1 sm:block" />
      {onDismiss && (
        <button type="button" aria-label={t("home.notice.dismiss")} onClick={onDismiss} className="shrink-0 rounded p-1 hover:bg-black/10">
          <X className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
