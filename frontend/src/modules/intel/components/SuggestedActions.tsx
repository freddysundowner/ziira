import { useState } from "react";

import { Alert, api, Card, ErrorState, Skeleton, unwrap, useQuery, useTranslation } from "@/sdk";

import { ApproveDialog, RejectDialog } from "../actions/DecisionDialogs";
import { type Proposal, splitProposals } from "../actions/logic";
import ProposalButtons from "../actions/ProposalButtons";
import { ProposalDecision, ProposalFacts, ProposalOutcome, ProposalStatusBadge } from "../actions/ProposalParts";
import { useActionLevel } from "../actions/useActionLevel";

/** The actions Intelligence has prepared for one finding. Hidden when there are none and suggestions are not switched on. */
export default function SuggestedActions({ findingId, companyId }: { findingId: string; companyId: string | undefined }) {
  const { t } = useTranslation("intel");
  const level = useActionLevel(companyId);
  const [approving, setApproving] = useState<Proposal | null>(null);
  const [rejecting, setRejecting] = useState<Proposal | null>(null);
  const q = useQuery({
    queryKey: ["intel", "proposals", "finding", findingId],
    queryFn: () => unwrap(api.GET("/api/v1/intel/findings/{finding_id}/actions", { params: { path: { finding_id: findingId } } })),
  });

  if (q.error) return <Card title={t("proposal.cardTitle")}><ErrorState message={q.error.message} onRetry={() => void q.refetch()} /></Card>;
  if (!q.data) return <Skeleton className="h-24 w-full" />;
  if (q.data.length === 0 && (level ?? 0) < 3) return null;
  const { waiting, earlier } = splitProposals(q.data);

  return (
    <Card title={t("proposal.cardTitle")} description={t("proposal.cardHint")}>
      <div className="space-y-4">
        {q.data.length === 0 && <p className="text-sm text-muted">{t("proposal.none")}</p>}
        {waiting.map((p) => (
          <article key={p.id} className="space-y-3 rounded-lg border border-line p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold">{p.action_title}</h3>
              <ProposalStatusBadge status={p.status} />
            </div>
            <ProposalFacts proposal={p} />
            {p.status === "failed" && <Alert tone="bad"><ProposalOutcome result={p.result} /></Alert>}
            <ProposalButtons proposal={p} onApprove={() => setApproving(p)} onReject={() => setRejecting(p)} />
          </article>
        ))}
        {earlier.length > 0 && (
          <details className="rounded-lg border border-line px-3 py-2">
            <summary className="cursor-pointer text-sm font-medium">{t("proposal.earlier", { count: earlier.length })}</summary>
            <ul className="mt-3 divide-y divide-line">
              {earlier.map((p) => (
                <li key={p.id} className="space-y-2 py-3 first:pt-0 last:pb-0">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="text-sm font-semibold">{p.action_title}</h3>
                    <ProposalStatusBadge status={p.status} />
                  </div>
                  <p className="text-sm">{p.description}</p>
                  {p.status === "executed" && <ProposalOutcome result={p.result} />}
                  <ProposalDecision proposal={p} />
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
      <ApproveDialog proposal={approving} onClose={() => setApproving(null)} />
      <RejectDialog proposal={rejecting} onClose={() => setRejecting(null)} />
    </Card>
  );
}
