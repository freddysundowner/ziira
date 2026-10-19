import { useState } from "react";

import { api, Badge, DataTable, Field, formatDate, Input, Pager, Select, today, unwrap, usePagedList, useTranslation } from "@/sdk";

import { formatDuration, monthStartOf } from "../lib";
import type { Project } from "../types";
import { DownloadButton } from "./DownloadButton";

/** Every time entry of the project, with filters and a spreadsheet download. */
export function ProjectTime({ project }: { project: Project }) {
  const { t } = useTranslation("timebilling");
  const [from, setFrom] = useState(() => project.starts_on && project.starts_on > monthStartOf(today(), -2) ? project.starts_on : monthStartOf(today(), -2));
  const [to, setTo] = useState(() => today());
  const [status, setStatus] = useState("");
  const [billable, setBillable] = useState("");
  const list = usePagedList(["timebilling", "project-entries", project.id, from, to, status, billable], (limit, offset) =>
    unwrap(api.GET("/api/v1/timebilling/entries", { params: { query: {
      project_id: project.id, date_from: from || undefined, date_to: to || undefined, status: (status || undefined) as "draft" | undefined,
      billable: billable === "" ? undefined : billable === "yes", limit, offset } } })), 25);
  const range = !!from && !!to;
  const toolbar = (
    <div className="flex flex-wrap items-end gap-3">
      <Field label={t("from")}><Input type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} /></Field>
      <Field label={t("to")}><Input type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} /></Field>
      <Field label={t("status")}>
        <Select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t("projects.allStatuses")}</option>
          {(["draft", "submitted", "approved"] as const).map((s) => <option key={s} value={s}>{t(`entries.status.${s}`)}</option>)}
        </Select>
      </Field>
      <Field label={t("billable")}>
        <Select value={billable} onChange={(e) => setBillable(e.target.value)}>
          <option value="">{t("entries.either")}</option><option value="yes">{t("entries.billableOnly")}</option><option value="no">{t("entries.notBillableOnly")}</option>
        </Select>
      </Field>
      {range && (
        <DownloadButton fileName="time.csv" request={() => api.GET("/api/v1/timebilling/reports/entries.csv", { params: { query: { date_from: from, date_to: to, project_id: project.id } }, parseAs: "blob" })}>{t("entries.download")}</DownloadButton>
      )}
    </div>
  );
  return (
    <DataTable
      rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(e) => e.id} toolbar={toolbar}
      empty={{ title: t("entries.noneProject"), hint: t("entries.noneProjectHint") }}
      columns={[
        { header: t("date"), sortValue: (e) => e.work_date, cell: (e) => formatDate(e.work_date) },
        { header: t("entries.person"), cell: (e) => e.user_name },
        { header: t("task"), hideBelow: "md", cell: (e) => <span><span className="font-medium">{e.task ?? "—"}</span>{e.note && <span className="block max-w-xs truncate text-xs text-muted">{e.note}</span>}</span> },
        { header: t("time"), align: "right", cell: (e) => <span className="tnum">{formatDuration(e.minutes)}</span> },
        { header: t("billable"), hideBelow: "sm", cell: (e) => (e.billable ? t("yes") : t("no")) },
        { header: t("status"), cell: (e) => (e.invoice_id ? <Badge tone="ok">{t("entries.invoiced")}</Badge> : e.in_review ? <Badge tone="info">{t("entries.inReview")}</Badge> : <Badge tone={e.status === "approved" ? "ok" : e.status === "submitted" ? "warn" : "neutral"}>{t(`entries.status.${e.status}`)}</Badge>) },
      ]}
      footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />} />
  );
}
