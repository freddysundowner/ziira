import { useState } from "react";
import { Link } from "react-router-dom";

import { api, Card, EmptyState, ErrorState, SkeletonRows, unwrap, useCompany, useQuery, useTranslation } from "@/sdk";

import { ApproveDialog, RejectDialog } from "./DecisionDialogs";
import { type Proposal } from "./logic";
import ProposalButtons from "./ProposalButtons";
import { ProposalFacts, ProposalStatusBadge } from "./ProposalParts";
import { SeverityBadge } from "../components/Badges";
import { ageInDays } from "../logic";

/** Suggestions this person may decide, newest first. */
export default function WaitingTab() {
  const { t } = useTranslation("intel");
  const { companies } = useCompany();
  const [approving, setApproving] = useState<Proposal | null>(null);
  const [rejecting, setRejecting] = useState<Proposal | null>(null);
  const q = useQuery({
    queryKey: ["intel", "proposals", "waiting"],
    queryFn: () => unwrap(api.GET("/api/v1/intel/actions", { params: { query: { mine: true, status: ["proposed", "failed"], limit: 100 } } })),
  });
  const branchName = (id: string | null) => companies.flatMap((c) => c.branches).find((b) => b.id === id)?.name;

  if (q.error) return <ErrorState message={q.error.message} onRetry={() => void q.refetch()} />;
  if (!q.data) return <SkeletonRows rows={4} cols={2} />;
  if (q.data.length === 0) return <Card><EmptyState title={t("actionsPage.nothingWaiting")} hint={t("actionsPage.nothingWaitingHint")} /></Card>;

  return (
    <>
      <ul className="space-y-3">
        {q.data.map((p) => (
          <li key={p.id}>
            <Card>
              <div className="space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={p.finding_severity} />
                  <ProposalStatusBadge status={p.status} />
                  <h2 className="text-sm font-semibold">{p.action_title}</h2>
                </div>
                <p className="text-xs text-muted">
                  <Link to={`/findings/${p.finding_id}`} className="underline">{p.finding_summary ?? t("noSummary")}</Link>
                  {branchName(p.branch_id) ? ` · ${branchName(p.branch_id)}` : ""} · {t("actionsPage.age", { count: ageInDays(p.proposed_at) })}
                </p>
                <ProposalFacts proposal={p} />
                <ProposalButtons proposal={p} onApprove={() => setApproving(p)} onReject={() => setRejecting(p)} compact />
              </div>
            </Card>
          </li>
        ))}
      </ul>
      <ApproveDialog proposal={approving} onClose={() => setApproving(null)} />
      <RejectDialog proposal={rejecting} onClose={() => setRejecting(null)} />
    </>
  );
}
