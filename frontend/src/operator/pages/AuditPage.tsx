import { Download } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Badge, Button, type Column, DataTable, Field, formatDate, Input, PageHeader, Pager, type Schemas, Select, toast, useDebounced, usePagedList, useTranslation } from "@/sdk";

import { opApi, opDownload, opUnwrap, saveBlob } from "../client";
import { actionLabel, auditQuery, type AuditFilters, exportPath, hasFilters, NO_FILTERS, rangeProblem } from "../helpers/audit";

type Line = Schemas["AuditLine"];
const TONES: Record<string, "ok" | "warn" | "bad"> = { ok: "ok", refused: "warn", failed: "bad" };
const PAGE = 50;

/** System > Audit trail: everything operators did on the platform, with filters (who, what, which subscriber, outcome, dates) and a CSV download. */
export default function AuditPage() {
  const { t } = useTranslation("operator");
  const [params] = useSearchParams();
  const [filters, setFilters] = useState<AuditFilters>({ ...NO_FILTERS, target: params.get("target") ?? "", operator: params.get("operator") ?? "" });
  const [exporting, setExporting] = useState(false);
  const typed = useDebounced(filters);
  const bad = rangeProblem(typed);
  const query = bad ? auditQuery({ ...typed, from: "", to: "" }) : auditQuery(typed);
  const list = usePagedList<Line>(["operator", "audit", query], (limit, offset) =>
    opUnwrap(opApi.GET("/api/v1/operator/audit", { params: { query: { ...query, limit, offset } } })).then((r) => r.items), PAGE);

  const set = (key: keyof AuditFilters) => (value: string) => setFilters((f) => ({ ...f, [key]: value }));
  async function download() {
    setExporting(true);
    try {
      saveBlob(await opDownload(exportPath(typed)), "audit-trail.csv");
      toast(t("audit.exported"), "ok");
    } catch (e) {
      toast(e instanceof Error ? e.message : t("audit.exportFailed"), "bad");
    } finally {
      setExporting(false);
    }
  }

  const columns: Column<Line>[] = [
    { header: t("audit.when"), cell: (l) => <span className="whitespace-nowrap text-sm">{formatDate(l.occurred_at, true)}</span> },
    { header: t("audit.operator"), cell: (l) => <span className="text-sm font-medium">{l.operator_name}</span> },
    { header: t("audit.action"), cell: (l) => <span className="text-sm">{t(`audit.actions.${l.action}`, { defaultValue: actionLabel(l.action) })}<span className="block font-mono text-[11px] text-muted">{l.action}</span></span> },
    { header: t("audit.target"), hideBelow: "sm", cell: (l) => <span className="break-all font-mono text-xs">{l.target ?? "-"}</span> },
    { header: t("audit.outcome"), cell: (l) => <Badge tone={TONES[l.outcome] ?? "neutral"}>{t(`audit.outcomes.${l.outcome}`, l.outcome)}</Badge> },
    { header: t("audit.reason"), hideBelow: "lg", cell: (l) => <span className="text-sm text-muted">{l.reason ?? ""}</span> },
  ];

  return (
    <>
      <PageHeader title={t("audit.title")} description={t("audit.description")}
        actions={<Button variant="secondary" loading={exporting} onClick={() => void download()}><Download className="h-4 w-4" /> {t("audit.export")}</Button>} />
      <div className="mb-4 grid gap-3 rounded-xl border border-line bg-surface p-3 sm:grid-cols-2 lg:grid-cols-6">
        <Field label={t("audit.operator")}><Input value={filters.operator} maxLength={100} onChange={(e) => set("operator")(e.target.value)} /></Field>
        <Field label={t("audit.action")}><Input value={filters.action} maxLength={100} placeholder="plan." onChange={(e) => set("action")(e.target.value)} /></Field>
        <Field label={t("audit.target")} hint={t("audit.targetHint")}><Input value={filters.target} maxLength={200} onChange={(e) => set("target")(e.target.value)} /></Field>
        <Field label={t("audit.outcome")}>
          <Select value={filters.outcome} onChange={(e) => set("outcome")(e.target.value)}>
            <option value="">{t("audit.anyOutcome")}</option>
            {["ok", "refused", "failed"].map((o) => <option key={o} value={o}>{t(`audit.outcomes.${o}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("audit.from")}><Input type="date" value={filters.from} onChange={(e) => set("from")(e.target.value)} /></Field>
        <Field label={t("audit.to")} error={rangeProblem(filters) ? t("audit.rangeProblem") : null}><Input type="date" value={filters.to} invalid={rangeProblem(filters)} onChange={(e) => set("to")(e.target.value)} /></Field>
        {hasFilters(filters) && <div className="sm:col-span-2 lg:col-span-6"><Button size="sm" variant="ghost" onClick={() => setFilters(NO_FILTERS)}>{t("audit.clear")}</Button></div>}
      </div>
      <DataTable rows={list.rows} columns={columns} rowKey={(l) => String(l.id)} dense loading={list.query.isPending}
        error={list.query.isError ? list.query.error.message : null} onRetry={() => void list.query.refetch()}
        empty={{ title: hasFilters(typed) ? t("audit.noMatch") : t("audit.empty"), hint: hasFilters(typed) ? t("audit.noMatchHint") : t("audit.emptyHint") }}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />} />
    </>
  );
}
