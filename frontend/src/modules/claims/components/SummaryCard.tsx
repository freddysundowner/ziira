import { AlertTriangle } from "lucide-react";

import { Alert, Button, Card, DetailList, formatDate, money, useTranslation } from "@/sdk";

import type { Claim } from "../types";
import { WaitingBadge } from "./StatusBits";

/** The right-hand summary: who pays what, who the claim waits for, the payer's papers and the work gate. */
export function SummaryCard({ claim, currency, canManage, onAuthority, onWorkDecision }: { claim: Claim; currency: string | undefined; canManage: boolean; onAuthority: () => void; onWorkDecision: () => void }) {
  const { t } = useTranslation("claims");
  const x = claim.totals;
  const gate = claim.gate;
  return (
    <div className="space-y-4">
      <Card title={t("summary.money")}>
        <dl className="tnum space-y-1.5 text-sm">
          <div className="flex justify-between"><dt className="text-muted">{t("summary.asked")}</dt><dd>{money(x.asked, currency)}</dd></div>
          <div className="flex justify-between"><dt className="text-muted">{t("summary.payerPays", { payer: claim.payer_name })}</dt><dd className="font-semibold">{money(x.payer_pays, currency)}</dd></div>
          <div className="flex justify-between"><dt className="text-muted">{t("summary.customerPays")}</dt><dd>{money(x.customer_pays, currency)}</dd></div>
          <div className="flex justify-between"><dt className="text-muted">{t("summary.excess")}</dt><dd>{money(claim.excess_amount, currency)}</dd></div>
          {Number(x.open) > 0 && <div className="flex justify-between"><dt className="text-muted">{t("summary.open")}</dt><dd>{money(x.open, currency)}</dd></div>}
          {Number(x.absorbed) > 0 && <div className="flex justify-between"><dt className="text-muted">{t("summary.absorbed")}</dt><dd>{money(x.absorbed, currency)}</dd></div>}
        </dl>
        {claim.waiting_on && <p className="mt-3 flex items-center gap-2 text-sm">{t("summary.waitingFor")} <WaitingBadge waiting={claim.waiting_on} /></p>}
      </Card>
      {(gate.state === "waiting_for_payer" || gate.state === "partly_authorised") && claim.status !== "closed" && (
        <Alert tone={gate.allowed ? "warn" : "bad"}>
          <p className="flex items-start gap-1.5"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><span>{gate.message}</span></p>
          {canManage && !gate.decision_recorded && <Button className="mt-2" size="sm" variant="secondary" onClick={onWorkDecision}>{t("summary.goAhead")}</Button>}
        </Alert>
      )}
      <Card title={t("summary.about")}>
        <DetailList items={[
          { label: t("new.policy"), value: claim.policy_number ?? "—" },
          { label: t("new.claimNo"), value: claim.claim_number ?? "—" },
          ...(claim.member_number ? [{ label: t("new.member"), value: claim.member_number }] : []),
          ...(claim.preauth_ref ? [{ label: t("new.preauth"), value: claim.preauth_ref }] : []),
          { label: t("new.loss"), value: claim.loss_date ? formatDate(claim.loss_date) : "—" },
          { label: t("new.assessor"), value: claim.assessor_name ? `${claim.assessor_name}${claim.assessor_phone ? ` · ${claim.assessor_phone}` : ""}` : "—" },
          { label: t("summary.authority"), value: claim.authority_ref ? `${claim.authority_ref}${claim.authority_amount ? ` · ${money(claim.authority_amount, currency)}` : ""}` : "—" },
          { label: t("summary.completed"), value: claim.completed_at ? `${claim.completion_signed_by ?? ""} · ${formatDate(claim.completion_signed_at ?? claim.completed_at, true)}` : "—" },
        ]} />
        {canManage && claim.status !== "closed" && <Button className="mt-3" size="sm" variant="ghost" onClick={onAuthority}>{claim.authority_ref ? t("summary.changeAuthority") : t("summary.addAuthority")}</Button>}
        {claim.loss_description && <p className="mt-3 whitespace-pre-line text-sm text-muted">{claim.loss_description}</p>}
        {claim.closed_note && <p className="mt-3 whitespace-pre-line text-sm text-muted">{claim.closed_note}</p>}
      </Card>
      {claim.required_documents.length > 0 && (
        <Card title={t("summary.documents")} description={t("summary.documentsHint")}>
          <ul className="list-disc pl-5 text-sm">{claim.required_documents.map((d) => <li key={d}>{d}</li>)}</ul>
        </Card>
      )}
    </div>
  );
}
