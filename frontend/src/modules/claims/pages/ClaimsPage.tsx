import { Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Button, type Column, DataTable, Field, formatDate, Input, money, PageHeader, Select, useCan, useDebounced, useTranslation } from "@/sdk";

import { NewClaimDialog } from "../components/NewClaimDialog";
import { PayerSelect } from "../components/pickers";
import { ClaimStatusBadge, WaitingBadge } from "../components/StatusBits";
import { type ClaimFilters, NO_FILTERS, useClaimList, useClaimsCompany } from "../hooks";
import { STATUSES, type ClaimSummary } from "../types";

/** All the claims: filter by payer, status and who they wait for. Click one to open it. */
export default function ClaimsPage() {
  const { t } = useTranslation("claims");
  const navigate = useNavigate();
  const { companyId, currency, isLoading } = useClaimsCompany();
  const canManage = useCan("claims.manage");
  const [filters, setFilters] = useState<ClaimFilters>(NO_FILTERS);
  const [creating, setCreating] = useState(false);
  const search = useDebounced(filters.search.trim());
  const list = useClaimList(companyId, filters, search);
  const rows = useMemo(() => (list.data ?? []).filter((c) => !filters.waiting || c.waiting_on === filters.waiting), [list.data, filters.waiting]);
  const set = (patch: Partial<ClaimFilters>) => setFilters((f) => ({ ...f, ...patch }));
  const columns: Column<ClaimSummary>[] = [
    { header: t("list.claim"), sortValue: (c) => c.number, cell: (c) => <span><span className="font-medium">{c.number}</span><span className="block text-xs text-muted">{[c.subject, c.insured_name].filter(Boolean).join(" · ")}</span></span> },
    { header: t("list.payer"), sortValue: (c) => c.payer_name, cell: (c) => <span>{c.payer_name}{c.claim_number ? <span className="block text-xs text-muted">{c.claim_number}</span> : null}</span> },
    { header: t("list.status"), sortValue: (c) => c.status, cell: (c) => <span className="inline-flex flex-wrap items-center gap-1"><ClaimStatusBadge status={c.status} reason={c.closed_reason} /><WaitingBadge waiting={c.waiting_on} /></span> },
    { header: t("list.asked"), align: "right", hideBelow: "md", sortValue: (c) => Number(c.totals.asked), cell: (c) => <span className="tnum">{money(c.totals.asked, currency)}</span> },
    { header: t("list.payerPays"), align: "right", hideBelow: "md", sortValue: (c) => Number(c.totals.payer_pays), cell: (c) => <span className="tnum">{money(c.totals.payer_pays, currency)}</span> },
    { header: t("list.customerPays"), align: "right", hideBelow: "lg", sortValue: (c) => Number(c.totals.customer_pays), cell: (c) => <span className="tnum">{money(c.totals.customer_pays, currency)}</span> },
    { header: t("list.opened"), hideBelow: "lg", sortValue: (c) => c.created_at, cell: (c) => formatDate(c.created_at) },
  ];
  return (
    <>
      <PageHeader title={t("menu.claims")} description={t("list.hint")}
        actions={canManage && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("list.new")}</Button>} />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label={t("list.search")}><Input value={filters.search} placeholder={t("list.searchHint")} onChange={(e) => set({ search: e.target.value })} /></Field>
        <Field label={t("list.payer")}><PayerSelect companyId={companyId} value={filters.payerId} onChange={(v) => set({ payerId: v })} all={t("list.allPayers")} onlyActive={false} /></Field>
        <Field label={t("list.status")}>
          <Select value={filters.status} onChange={(e) => set({ status: e.target.value })}>
            <option value="">{t("list.allStatuses")}</option>
            {STATUSES.map((s) => <option key={s} value={s}>{t(`status.${s}`)}</option>)}
          </Select>
        </Field>
        <Field label={t("list.waiting")}>
          <Select value={filters.waiting} onChange={(e) => set({ waiting: e.target.value })}>
            <option value="">{t("list.anyone")}</option>
            {["payer", "us", "customer"].map((w) => <option key={w} value={w}>{t(`waiting.${w}`)}</option>)}
          </Select>
        </Field>
      </div>
      <DataTable rows={rows} columns={columns} rowKey={(c) => c.id} rowHref={(c) => `/claims/${c.id}`} loading={isLoading || list.isLoading}
        error={list.error?.message ?? null} onRetry={() => void list.refetch()}
        empty={{ title: filters.status || filters.payerId || search || filters.waiting ? t("list.noMatch") : t("list.empty"), hint: filters.status || filters.payerId || search || filters.waiting ? t("list.noMatchHint") : t("list.emptyHint"),
          action: canManage && !(filters.status || filters.payerId || search) ? <Button onClick={() => setCreating(true)}>{t("list.new")}</Button> : undefined }} />
      {creating && <NewClaimDialog open onClose={() => setCreating(false)} onCreated={(c) => navigate(`/claims/${c.id}`)} />}
    </>
  );
}
