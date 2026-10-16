import { useState } from "react";
import { Link } from "react-router-dom";

import { api, DataTable, formatDate, Pager, Select, unwrap, usePagedList, useTranslation } from "@/sdk";

import { HISTORY } from "./logic";
import { ProposalStatusBadge } from "./ProposalParts";

type Status = (typeof HISTORY)[number];

/** Suggestions that are no longer waiting, with who decided and how it ended. */
export default function HistoryTab() {
  const { t } = useTranslation("intel");
  const [status, setStatus] = useState<"" | Status>("");
  const list = usePagedList(["intel", "proposals", "history", status], (limit, offset) => unwrap(api.GET("/api/v1/intel/actions", {
    params: { query: { status: status ? [status] : [...HISTORY], limit, offset } },
  })));
  return (
    <DataTable
      rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(p) => p.id}
      rowHref={(p) => `/intelligence/things/${p.finding_id}`}
      toolbar={
        <Select aria-label={t("status.label")} className="w-auto" value={status} onChange={(e) => setStatus(e.target.value as "" | Status)}>
          <option value="">{t("actionsPage.allOutcomes")}</option>
          {HISTORY.map((x) => <option key={x} value={x}>{t(`proposal.status.${x}`)}</option>)}
        </Select>
      }
      empty={{ title: t("actionsPage.noHistory"), hint: t("actionsPage.noHistoryHint") }}
      columns={[
        { header: t("actionsPage.what"), cell: (p) => (
          <div className="min-w-0">
            <p className="font-medium">{p.action_title}</p>
            <Link to={`/intelligence/things/${p.finding_id}`} className="text-xs text-muted hover:underline">{p.finding_summary ?? t("noSummary")}</Link>
          </div>
        ) },
        { header: t("status.label"), cell: (p) => <ProposalStatusBadge status={p.status} /> },
        { header: t("actionsPage.decidedBy"), hideBelow: "sm", cell: (p) => p.decided_by_name ?? t("bySystem") },
        { header: t("actionsPage.when"), hideBelow: "md", cell: (p) => formatDate(p.decided_at ?? p.proposed_at, true) },
        { header: t("actionsPage.outcome"), hideBelow: "lg", cell: (p) => p.result?.message ?? p.decision_note ?? "—" },
      ]}
      footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
    />
  );
}
