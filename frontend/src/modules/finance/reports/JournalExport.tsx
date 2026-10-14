import { useState } from "react";

import { api, Card, Field, Select, useTranslation } from "@/sdk";

import { CsvButton } from "../components/CsvButton";
import type { ReportProps } from "./types";

type Layout = "generic" | "quickbooks" | "sage";

/** The journal lines of the chosen dates as a file for the accountant's software. */
export function JournalExport({ scope, from, to }: ReportProps) {
  const { t } = useTranslation("finance");
  const [layout, setLayout] = useState<Layout>("generic");
  return (
    <Card title={t("reports.export")} description={t("exportHint")}>
      <div className="max-w-md space-y-4">
        <Field label={t("exportLayout")} hint={t(`exportLayouts.${layout}Hint`)}>
          <Select value={layout} onChange={(e) => setLayout(e.target.value as Layout)}>
            {(["generic", "quickbooks", "sage"] as const).map((l) => <option key={l} value={l}>{t(`exportLayouts.${l}`)}</option>)}
          </Select>
        </Field>
        <CsvButton label={t("downloadJournal")} fallbackName={`journal-${layout}.csv`}
          request={() => api.GET("/api/v1/finance/exports/journal", { params: { query: { company_id: scope.companyId, date_from: from, date_to: to, format: layout, branch_id: scope.branchId || undefined } }, parseAs: "blob" })} />
      </div>
    </Card>
  );
}
