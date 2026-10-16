import { useState } from "react";
import { Link } from "react-router-dom";

import { api, Badge, Card, DataTable, formatDate, Pager, Select, unwrap, usePagedList, useQuery, useTranslation } from "@/sdk";

import { ProposalOutcome } from "../actions/ProposalParts";

/** The record of every action taken, by a person or by Intelligence under a rule. */
export default function ActionLog({ companyId }: { companyId: string }) {
  const { t } = useTranslation("intel");
  const [mode, setMode] = useState<"" | "manual" | "automatic">("");
  const [type, setType] = useState("");
  const types = useQuery({ queryKey: ["intel", "action-types"], queryFn: () => unwrap(api.GET("/api/v1/intel/actions/types")), staleTime: 300_000 });
  const list = usePagedList(["intel", "action-log", companyId, mode, type], (limit, offset) => unwrap(api.GET("/api/v1/intel/actions/log", {
    params: { query: { company_id: companyId, mode: mode || undefined, action_type: type || undefined, limit, offset } },
  })), 20);
  return (
    <Card title={t("log.title")} description={t("log.hint")} flush>
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(r) => r.id} dense
        toolbar={
          <div className="flex flex-wrap gap-2">
            <Select aria-label={t("log.mode")} className="w-auto" value={mode} onChange={(e) => setMode(e.target.value as "" | "manual" | "automatic")}>
              <option value="">{t("log.anyMode")}</option>
              <option value="manual">{t("log.manual")}</option>
              <option value="automatic">{t("log.automatic")}</option>
            </Select>
            <Select aria-label={t("log.actionType")} className="w-auto" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">{t("log.anyAction")}</option>
              {(types.data ?? []).map((a) => <option key={a.type} value={a.type}>{a.title}</option>)}
            </Select>
          </div>
        }
        empty={{ title: t("log.none"), hint: t("log.noneHint") }}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
        columns={[
          { header: t("log.when"), cell: (r) => formatDate(r.created_at, true) },
          { header: t("log.what"), cell: (r) => (
            <div className="min-w-0">
              <p className="font-medium">{r.action_title}</p>
              <p className="text-sm text-muted">{r.result ? <ProposalOutcome result={r.result} /> : r.message}</p>
              {r.finding_id && <Link to={`/intelligence/things/${r.finding_id}`} className="text-xs text-muted hover:underline">{r.finding_summary ?? t("noSummary")}</Link>}
            </div>
          ) },
          { header: t("log.who"), hideBelow: "sm", cell: (r) => (r.actor_name ?? (r.mode === "automatic" ? t("log.byRule") : t("bySystem"))) },
          { header: t("log.outcome"), cell: (r) => <Badge tone={r.outcome === "executed" ? "ok" : "bad"}>{t(`log.outcomes.${r.outcome}`)}</Badge> },
        ]} />
    </Card>
  );
}
