import { Badge, type Column, DataTable, formatDate, type Schemas, useTranslation } from "@/sdk";

type Line = Schemas["TrailLine"];

/** What operators did to this subscriber (from the operator trail). */
export function AuditTab({ lines }: { lines: Line[] }) {
  const { t } = useTranslation("operator");
  const columns: Column<Line>[] = [
    { header: t("operators.when"), cell: (l) => <span className="text-sm">{formatDate(l.occurred_at, true)}</span> },
    { header: t("operators.who"), hideBelow: "sm", cell: (l) => <span className="text-sm">{l.operator_name}</span> },
    { header: t("operators.action"), cell: (l) => <span className="font-mono text-xs">{l.action}</span> },
    { header: t("operators.outcome"), cell: (l) => <Badge tone={l.outcome === "ok" ? "ok" : l.outcome === "refused" ? "warn" : "bad"}>{l.outcome}</Badge> },
    { header: t("operators.reason"), hideBelow: "md", cell: (l) => <span className="text-xs text-muted">{l.reason ?? ""}</span> },
  ];
  return <DataTable rows={lines} columns={columns} rowKey={(l) => String(l.id)} dense pageSize={15} empty={{ title: t("subscriber.audit.empty"), hint: t("subscriber.audit.emptyHint") }} />;
}
