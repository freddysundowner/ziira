import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { useTranslation } from "@/sdk";

import { SyncChip } from "./SyncChip";

/**
 * The terminal fills the whole window above the app shell (no sidebar), so a cashier sees only the sale.
 * The bar carries the way back to the office and whatever the screen puts in it.
 */
export function Frame({ children, info, actions }: { children: ReactNode; info?: ReactNode; actions?: ReactNode }) {
  const { t } = useTranslation("pos");
  return (
    <div className="fixed inset-0 z-40 flex flex-col bg-bg text-ink">
      <header className="no-print flex h-14 shrink-0 items-center gap-2 border-b border-line bg-surface px-3">
        <Link to="/" aria-label={t("terminal.backToOffice")} className="inline-flex h-10 items-center gap-1.5 rounded-lg px-2.5 text-sm font-medium text-muted hover:bg-sunken hover:text-ink">
          <ArrowLeft className="h-4 w-4" /><span className="hidden sm:inline">{t("terminal.backToOffice")}</span>
        </Link>
        <div className="min-w-0 flex-1 truncate text-sm text-muted">{info}</div>
        <SyncChip />
        <div className="flex shrink-0 items-center gap-1.5">{actions}</div>
      </header>
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </div>
  );
}

export function Centered({ children }: { children: ReactNode }) {
  return <div className="flex flex-1 items-start justify-center overflow-y-auto p-4 sm:items-center">{children}</div>;
}
