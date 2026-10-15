import { Button, humanise, useTranslation } from "@/sdk";

import type { Proposal } from "./logic";

/** Approve and turn down. Someone who may not decide sees in plain words what is missing, not a dead button. */
export default function ProposalButtons({ proposal, onApprove, onReject, compact }: { proposal: Proposal; onApprove: () => void; onReject: () => void; compact?: boolean }) {
  const { t } = useTranslation("intel");
  const size = compact ? "sm" : "md";
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <Button size={size} disabled={!proposal.can_decide} onClick={onApprove}>{proposal.status === "failed" ? t("proposal.tryAgain") : t("proposal.approve")}</Button>
        <Button size={size} variant="secondary" disabled={!proposal.can_decide} onClick={onReject}>{t("proposal.reject")}</Button>
      </div>
      {!proposal.can_decide && <p className="text-xs text-muted">{t("proposal.cannotDecide", { permission: humanise(proposal.needs_permission.replace(/[._]/g, " ")) })}</p>}
    </div>
  );
}
