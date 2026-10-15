import { Link } from "react-router-dom";

import { Badge, type BadgeTone, DetailList, formatDate, humanise, useTranslation } from "@/sdk";

import { type Proposal, recordLink } from "./logic";

const TONE: Record<string, BadgeTone> = { proposed: "brand", approved: "info", executed: "ok", failed: "bad", rejected: "neutral", expired: "neutral", cancelled: "neutral" };

export function ProposalStatusBadge({ status }: { status: string }) {
  const { t } = useTranslation("intel");
  return <Badge tone={TONE[status] ?? "neutral"}>{t(`proposal.status.${status}`, humanise(status))}</Badge>;
}

/** What the suggestion says it will do, and the figures behind it. */
export function ProposalFacts({ proposal }: { proposal: Proposal }) {
  const facts = Object.entries(proposal.facts);
  return (
    <div className="space-y-3">
      <p className="text-sm">{proposal.description}</p>
      {facts.length > 0 && <DetailList items={facts.map(([label, value]) => ({ label, value }))} />}
    </div>
  );
}

/** The outcome of an approved suggestion: the message, and links to what it created. */
export function ProposalOutcome({ result: r }: { result: Proposal["result"] }) {
  const { t } = useTranslation("intel");
  if (!r) return null;
  return (
    <div className="space-y-1 text-sm">
      <p>{r.message}</p>
      {r.created.length > 0 && (
        <ul className="flex flex-wrap gap-x-3 gap-y-1">
          {r.created.map((c, i) => {
            const to = recordLink(c);
            return (
              <li key={`${c.type}-${c.id ?? i}`}>
                <span className="text-muted">{t(`record.${c.type.replace(/\./g, "_")}`, humanise(c.type.split(".").pop()))}: </span>
                {to ? <Link to={to} className="font-medium underline">{c.label}</Link> : <span>{c.label}</span>}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** Who decided, when, and what they wrote. */
export function ProposalDecision({ proposal }: { proposal: Proposal }) {
  const { t } = useTranslation("intel");
  const who = proposal.decided_by_name ?? t("bySystem");
  const when = proposal.decided_at ? formatDate(proposal.decided_at, true) : null;
  return (
    <div className="space-y-1 text-xs text-muted">
      <p>{t("proposal.proposedOn", { date: formatDate(proposal.proposed_at, true) })}</p>
      {when && <p>{t(`proposal.decidedBy.${proposal.status}`, { defaultValue: t("proposal.decidedBy.default"), who, date: when })}</p>}
      {proposal.decision_note && <p className="whitespace-pre-wrap text-sm text-ink">{proposal.decision_note}</p>}
    </div>
  );
}
