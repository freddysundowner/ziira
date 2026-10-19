import { CircleAlert, CircleCheck, CircleX, ScrollText, UserRound, Wallet } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Alert, Badge, Button, cx, Field, Input, money, useTranslation } from "@/sdk";

import { clockTime, type ResultView } from "../gymLogic";
import { credits } from "../logic";
import { personPath } from "../public";
import { PersonPhoto } from "./PersonPhoto";

const BANNER = {
  allow: { box: "bg-ok text-ok-ink", Icon: CircleCheck },
  warn: { box: "bg-warn text-bg", Icon: CircleAlert },
  deny: { box: "bg-bad text-bad-ink", Icon: CircleX },
} as const;

/** The answer to a check-in: a big allow / warn / deny banner, every reason, who it is, and what to do next. */
export function ResultPanel({ view, currency, busy, onOverride, onAcceptTerms }: {
  view: ResultView; currency?: string; busy?: boolean; onOverride: (reason: string) => void; onAcceptTerms: () => void;
}) {
  const { t } = useTranslation("memberships");
  const [reason, setReason] = useState("");
  const { box, Icon } = BANNER[view.outcome];
  const person = view.customerId;
  return (
    <section aria-live="assertive" aria-label={t("checkin.resultLabel")} className="overflow-hidden rounded-xl border border-line bg-surface shadow-card">
      <div className={cx("flex items-center gap-3 px-5 py-4", box)}>
        <Icon className="h-9 w-9 shrink-0" aria-hidden="true" />
        <div className="min-w-0">
          <p className="text-3xl font-extrabold uppercase tracking-wide">{t(`checkin.banner.${view.outcome}`)}</p>
          {view.overridden && <p className="text-sm font-medium">{t("checkin.overridden")}</p>}
        </div>
      </div>
      <div className="space-y-4 p-5">
        {view.offlineSavedAt !== null && <Alert tone="warn">{t("checkin.offlineNotice", { time: clockTime(view.offlineSavedAt) })}</Alert>}
        <div className="flex items-center gap-4">
          {!view.notFound && <PersonPhoto url={view.photoUrl} name={view.name} size="md" />}
          <div className="min-w-0">
            {view.name && <p className="truncate text-2xl font-bold">{view.name}</p>}
            {view.number && <p className="font-mono text-sm text-muted">{view.number}</p>}
            {view.plan && <p className="text-sm">{view.plan}</p>}
          </div>
        </div>
        <p className="text-lg font-semibold">{view.headline}</p>
        {view.reasons.length > 0 && (
          <ul className="space-y-1.5">
            {view.reasons.map((r) => (
              <li key={`${r.code}-${r.message}`} className="flex items-start gap-2 text-sm">
                <Badge tone={r.level === "deny" ? "bad" : r.level === "warn" ? "warn" : "info"}>{t(`checkin.level.${r.level === "deny" || r.level === "warn" ? r.level : "info"}`)}</Badge>
                <span>{r.message}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
          {view.owed > 0 && <p className="font-semibold text-bad">{t("checkin.owed", { amount: money(view.owed, currency) })}</p>}
          {view.creditsLeft !== null && <p>{t("checkin.creditsLeft", { n: credits(view.creditsLeft) })}</p>}
        </div>
        {view.duplicate && <Alert tone="info">{t("checkin.alreadyIn")}</Alert>}

        {view.outcome === "deny" && view.canOverride && (
          <div className="space-y-2 rounded-lg border border-line bg-sunken p-3">
            <Field label={t("checkin.overrideReason")} hint={t("checkin.overrideHint")}>
              <Input value={reason} maxLength={300} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <Button size="lg" variant="danger" loading={busy} disabled={!reason.trim()} onClick={() => onOverride(reason.trim())}>{t("checkin.letInAnyway")}</Button>
          </div>
        )}
        {view.outcome === "deny" && view.offlineSavedAt !== null && <Alert tone="info">{t("checkin.overrideNeedsConnection")}</Alert>}

        {person && (
          <div className="flex flex-wrap gap-2">
            <Link to={personPath(person)} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-line px-4 text-sm font-medium hover:bg-sunken"><UserRound className="h-4 w-4" />{t("checkin.openMember")}</Link>
            {view.owed > 0 && (
              <Link to={`${personPath(person)}?tab=money`} className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-line px-4 text-sm font-medium hover:bg-sunken"><Wallet className="h-4 w-4" />{t("checkin.takePayment")}</Link>
            )}
            {view.needsTerms && view.offlineSavedAt === null && (
              <Button variant="secondary" className="min-h-11" onClick={onAcceptTerms}><ScrollText className="h-4 w-4" />{t("checkin.acceptTerms")}</Button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
