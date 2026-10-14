import { Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  api, Badge, Button, DataTable, formatDate, humanise, Input, money, PageHeader, Pager, Select, StatusBadge, Tabs, unwrap, useCan, usePagedList, useTranslation,
} from "@/sdk";

import { ScopeSelects, type Scope, useScope } from "../scope";

const STATUSES = ["draft", "pending_approval", "posted", "rejected"] as const;

/** The journal: every posted entry (from sales, stock, expenses and by hand), and the manual journals with their approval status. */
export default function JournalPage() {
  const { t } = useTranslation("finance");
  const scope = useScope();
  const canWrite = useCan("journal.post_manual");
  const [tab, setTab] = useState<"entries" | "manual">("entries");
  return (
    <>
      <PageHeader title={t("journal.title")} description={t("journal.hint")}
        actions={<>
          <ScopeSelects scope={scope} branch={false} />
          {canWrite && <Link to="/finance/manual-journals/new"><Button><Plus className="h-4 w-4" />{t("journal.newManual")}</Button></Link>}
        </>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "entries", label: t("journal.entries") }, { id: "manual", label: t("journal.manual") }]} />
      {tab === "entries" ? <Entries scope={scope} /> : <Manuals scope={scope} />}
    </>
  );
}

function Entries({ scope }: { scope: Scope }) {
  const { t } = useTranslation("finance");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const list = usePagedList(["finance", "entries", scope.companyId, from, to], (limit, offset) =>
    unwrap(api.GET("/api/v1/finance/journal-entries", { params: { query: { company_id: scope.companyId || undefined, date_from: from || undefined, date_to: to || undefined, limit, offset } } })));
  return (
    <DataTable
      rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(e) => e.id}
      rowHref={(e) => `/finance/journal/${e.id}`} searchText={(e) => `${e.number} ${e.description ?? ""} ${e.source_type ?? ""}`} searchPlaceholder={t("journal.search")}
      toolbar={<>
        <Input type="date" aria-label={t("from")} className="w-auto" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
        <Input type="date" aria-label={t("to")} className="w-auto" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
      </>}
      empty={{ title: t("journal.empty"), hint: t("journal.emptyHint") }}
      columns={[
        { header: t("number"), sortValue: (e) => e.number, cell: (e) => <span className="font-mono text-xs font-medium">{e.number}</span> },
        { header: t("date"), sortValue: (e) => e.entry_date, cell: (e) => formatDate(e.entry_date) },
        { header: t("description"), hideBelow: "sm", cell: (e) => e.description ?? "—" },
        { header: t("source"), hideBelow: "md", cell: (e) => (e.is_manual ? <Badge tone="brand">{t("journal.byHand")}</Badge> : <Badge>{humanise(e.source_type)}</Badge>) },
        { header: "", hideBelow: "md", cell: (e) => e.reversal_of_id && <Badge tone="warn">{t("journal.reversal")}</Badge> },
      ]}
      footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
    />
  );
}

function Manuals({ scope }: { scope: Scope }) {
  const { t } = useTranslation("finance");
  const [status, setStatus] = useState("");
  const list = usePagedList(["finance", "manuals", status], (limit, offset) =>
    unwrap(api.GET("/api/v1/finance/manual-journals", { params: { query: { status: status || undefined, limit, offset } } })));
  return (
    <DataTable
      rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(j) => j.id}
      rowHref={(j) => `/finance/manual-journals/${j.id}`}
      toolbar={
        <Select aria-label={t("status")} className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t("allStatuses")}</option>
          {STATUSES.map((s) => <option key={s} value={s}>{humanise(s)}</option>)}
        </Select>}
      empty={{ title: t("journal.noManual"), hint: t("journal.noManualHint") }}
      columns={[
        { header: t("number"), cell: (j) => <span className="font-mono text-xs font-medium">{j.number}</span> },
        { header: t("date"), cell: (j) => formatDate(j.entry_date) },
        { header: t("description"), hideBelow: "sm", cell: (j) => j.description },
        { header: t("total"), align: "right", cell: (j) => money(j.total, scope.companies.find((c) => c.id === j.company_id)?.currency ?? scope.currency) },
        { header: t("status"), cell: (j) => <StatusBadge status={j.status} /> },
      ]}
      footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
    />
  );
}
