import { ChevronDown } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Button, cx, formatDate, money, useCan, useTranslation } from "@/sdk";

import { bandOf, factsOf } from "../plainWords";
import { type Group } from "../useGrouped";
import { useNames } from "../useNames";
import { usePlain } from "../usePlain";
import AssignGroupDialog from "./AssignGroupDialog";
import { SeverityBadge } from "./Badges";
import FactChips from "./FactChips";
import NotAProblemDialog from "./NotAProblemDialog";
import SnoozeMenu from "./SnoozeMenu";

/**
 * One thing to look at, as a card: what it is in plain words, why it matters, a few facts, and three buttons. A group of
 * similar things (same kind, same branch, same day) is one card with a count and the members one click away.
 */
export default function ThingCard({ group, actions = true }: { group: Group; actions?: boolean }) {
  const { t } = useTranslation("intel");
  const plain = usePlain();
  const { branchName, currencyOf } = useNames();
  const canManage = useCan("findings.manage");
  const [open, setOpen] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [ignoring, setIgnoring] = useState(false);
  const top = group.members[0];
  const text = plain.check(group.check_code);
  const currency = currencyOf(group.company_id);
  const where = branchName(group.branch_id);
  const many = group.count > 1;
  const facts = factsOf(top.figures ?? {}, plain.data?.figures ?? {}, many ? 1 : 2);
  const headline = text?.title ?? top.summary ?? t("noSummary");
  const lead = [
    ...(many ? [{ label: t("card.howMany"), value: String(group.count) }] : []),
    ...(Number(group.amount) > 0 ? [{ label: t("card.involved"), value: money(group.amount, currency) }] : []),
  ];

  return (
    <article className={cx("rounded-xl border bg-surface p-4 shadow-card", bandOf(group.severity) === "urgent" ? "border-bad/40" : "border-line")}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
        <SeverityBadge severity={group.severity} />
        {text && <span>{plain.topicTitle(text.topic)}</span>}
        {where && <span>· {where}</span>}
        <span>· {formatDate(group.day)}</span>
        {top.snoozed_until && <span>· {t("card.snoozedUntil", { date: formatDate(top.snoozed_until) })}</span>}
      </div>
      <h3 className="mt-2 text-base font-semibold">
        <Link to={`/intelligence/things/${top.id}`} className="hover:underline">{headline}</Link>
      </h3>
      {!many && top.summary && <p className="mt-1 text-sm text-muted">{top.summary}</p>}
      {text?.why && <p className="mt-2 text-sm"><span className="font-medium">{t("card.why")} </span>{text.why}</p>}
      <div className="mt-3"><FactChips facts={facts} currency={currency} lead={lead} /></div>
      {actions && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Link to={`/intelligence/things/${top.id}`} className="inline-flex h-9 items-center rounded-lg bg-brand px-3.5 text-sm font-medium text-brand-ink hover:opacity-90">{t("card.lookInto")}</Link>
          {canManage && <Button variant="secondary" onClick={() => setAssigning(true)}>{t("action.assign")}</Button>}
          {canManage && <Button variant="ghost" onClick={() => setIgnoring(true)}>{t("action.dismiss")}</Button>}
          <SnoozeMenu findingId={top.id} />
        </div>
      )}
      {many && (
        <div className="mt-3 border-t border-line pt-2">
          <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="inline-flex items-center gap-1 text-sm font-medium text-brand-strong hover:underline">
            <ChevronDown className={cx("h-4 w-4 transition-transform", open && "rotate-180")} aria-hidden />{open ? t("card.hide") : t("card.showAll", { count: group.count })}
          </button>
          {open && (
            <ul className="mt-2 divide-y divide-line text-sm">
              {group.members.map((m) => (
                <li key={m.id} className="py-1.5"><Link to={`/intelligence/things/${m.id}`} className="hover:underline">{m.summary ?? t("noSummary")}</Link></li>
              ))}
              {group.count > group.members.length && <li className="py-1.5 text-muted">{t("card.andMore", { count: group.count - group.members.length })}</li>}
            </ul>
          )}
        </div>
      )}
      {actions && canManage && <AssignGroupDialog ids={group.members.map((m) => m.id)} open={assigning} onClose={() => setAssigning(false)} />}
      {actions && canManage && <NotAProblemDialog findingId={top.id} open={ignoring} onClose={() => setIgnoring(false)} />}
    </article>
  );
}
