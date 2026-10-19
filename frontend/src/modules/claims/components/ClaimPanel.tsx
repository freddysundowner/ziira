import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Alert, Button, Card, money, Skeleton, useCan, useTranslation } from "@/sdk";

import { useClaimOfSource, useClaimsCompany } from "../hooks";
import { NewClaimDialog } from "./NewClaimDialog";
import { ClaimStatusBadge, WaitingBadge } from "./StatusBits";

export interface ClaimPanelProps {
  sourceType: "job" | "appointment";
  sourceId: string;
  companyId: string;
  branchId?: string;
  customerId?: string | null;
  /** What the claim is about, put on the new claim ("Toyota Corolla KAA 123B"). */
  subject?: string | null;
}

/**
 * The claim of a job or appointment, in a small card for its page: nothing for people who cannot see claims; "an insurer pays"
 * with a button to open a claim when there is none; otherwise the state, who pays what and who the claim waits for, and a link.
 */
export function ClaimPanel({ sourceType, sourceId, companyId, branchId, customerId, subject }: ClaimPanelProps) {
  const { t } = useTranslation("claims");
  const navigate = useNavigate();
  const canView = useCan("claims.view");
  const canManage = useCan("claims.manage");
  const { currency } = useClaimsCompany();
  const found = useClaimOfSource(sourceType, sourceId);
  const [opening, setOpening] = useState(false);
  if (!canView && !canManage) return null;
  if (found.isLoading) return <Skeleton className="h-24 rounded-xl" />;
  const claim = found.data;
  return (
    <Card title={<span className="inline-flex items-center gap-2"><ShieldCheck className="h-4 w-4" />{t("panel.title")}</span>}>
      {!claim ? (
        <div className="space-y-3">
          <p className="text-sm text-muted">{t("panel.none")}</p>
          {canManage && <Button size="sm" variant="secondary" onClick={() => setOpening(true)}>{t("panel.open")}</Button>}
          {opening && (
            <NewClaimDialog open onClose={() => setOpening(false)} onCreated={(c) => navigate(`/claims/${c.id}`)}
              defaults={{ sourceType, sourceId, companyId, branchId, customerId: customerId ?? undefined, subject: subject ?? undefined }} />
          )}
        </div>
      ) : (
        <div className="space-y-3 text-sm">
          <p className="flex flex-wrap items-center gap-2"><Link className="font-semibold underline" to={`/claims/${claim.id}`}>{claim.number}</Link><ClaimStatusBadge status={claim.status} reason={claim.closed_reason} /><WaitingBadge waiting={claim.waiting_on} /></p>
          <p className="text-muted">{claim.payer_name}{claim.policy_number ? ` · ${claim.policy_number}` : ""}</p>
          <dl className="tnum grid grid-cols-2 gap-x-3 gap-y-1">
            <dt className="text-muted">{t("panel.payerPays")}</dt><dd className="text-right font-medium">{money(claim.totals.payer_pays, currency)}</dd>
            <dt className="text-muted">{t("panel.customerPays")}</dt><dd className="text-right">{money(claim.totals.customer_pays, currency)}</dd>
            {Number(claim.totals.open) > 0 && <><dt className="text-muted">{t("panel.undecided")}</dt><dd className="text-right">{money(claim.totals.open, currency)}</dd></>}
          </dl>
          {(claim.gate.state === "waiting_for_payer" || claim.gate.state === "partly_authorised") && claim.status !== "closed" && <Alert tone={claim.gate.allowed ? "warn" : "bad"}>{claim.gate.message}</Alert>}
          <Link to={`/claims/${claim.id}`}><Button size="sm" variant="secondary">{t("panel.view")}</Button></Link>
        </div>
      )}
    </Card>
  );
}
