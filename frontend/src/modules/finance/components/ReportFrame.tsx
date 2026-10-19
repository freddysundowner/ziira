import { Printer } from "lucide-react";
import type { ReactNode } from "react";

import { Button, Card, ErrorState, formatDate, Skeleton, useTranslation } from "@/sdk";

/** A report's card: a print-only heading (business, report, period), the print and CSV buttons, and loading / error states. */
export function ReportFrame({ title, company, period, actions, loading, error, onRetry, children }: {
  title: string; company: string; period: string; actions?: ReactNode; loading?: boolean; error?: string | null; onRetry?: () => void; children?: ReactNode;
}) {
  const { t } = useTranslation("finance");
  return (
    <Card className="print:border-0 print:shadow-none"
      actions={<div className="no-print flex min-w-0 max-w-full flex-wrap gap-2">{actions}<Button variant="secondary" onClick={() => window.print()}><Printer className="h-4 w-4" />{t("print")}</Button></div>}
      title={<span>{title}</span>} description={period}>
      <div className="mb-4 hidden print:block">
        <p className="text-lg font-semibold">{company}</p>
        <p className="text-sm">{title} · {period}</p>
        <p className="text-xs">{t("printedOn", { date: formatDate(new Date(), true) })}</p>
      </div>
      {error ? <ErrorState message={error} onRetry={onRetry} /> : loading ? <Skeleton className="h-48 w-full" /> : children}
    </Card>
  );
}
