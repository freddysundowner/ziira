import { Link } from "react-router-dom";

import { cx, Stat, useTranslation } from "@/sdk";

import { ageLabel, backupTone } from "../../lib";
import { Section } from "./Section";
import { useDashboardQueries } from "./queries";

/** Is the platform itself well: API ready, worker keeping up, jobs, backups, upgrades, mail, AI spend. Each tile links to where it is dealt with. */
export function SystemTiles() {
  const { t } = useTranslation("operator");
  const { system } = useDashboardQueries();
  return (
    <Section query={system} title={t("dash.system.title")} description={t("dash.system.hint")} errorTitle={t("dash.system.failed")} skeleton="h-56"
      actions={<Link to="/operator/health" className="text-xs font-medium text-brand-strong hover:underline">{t("dash.system.open")}</Link>}>
      {(s) => {
        const backup = backupTone(s.backup_age_hours);
        const cap = s.ai_cap_usd;
        return (
          <div className="grid grid-cols-2 gap-3">
            <Stat label={t("dash.system.api")} value={s.ready ? t("health.yes") : t("health.no")} tone={s.ready ? "ok" : "bad"} hint={s.ready ? t("dash.system.apiOk") : t("health.problemCount", { count: s.problems })} to="/operator/health" />
            <Stat label={t("dash.system.worker")} value={s.queues_known ? ageLabel(s.jobs_oldest_due_seconds) : "-"} tone={s.queues_known ? (s.jobs_oldest_due_seconds > 600 ? "bad" : "ok") : undefined}
              hint={s.queues_known ? t("dash.system.backlog", { due: s.jobs_due, outbox: s.outbox_pending }) : t("health.queuesUnavailable")} to="/operator/health" />
            <Stat label={t("dash.system.failedJobs")} value={s.queues_known ? s.failed_jobs : "-"} tone={s.failed_jobs > 0 ? "bad" : s.queues_known ? "ok" : undefined} to="/operator/health" />
            <Stat label={t("dash.system.backup")} value={s.backup_reported ? ageLabel((s.backup_age_hours ?? 0) * 3600) : t("health.notReported")}
              tone={s.backup_reported ? (backup === "ok" ? "ok" : "bad") : undefined} hint={t("dash.system.backupHint")} to="/operator/backups" />
            <Stat label={t("dash.system.upgrades")} value={s.businesses_behind} tone={s.businesses_behind ? "bad" : "ok"} hint={s.businesses_unreadable ? t("dash.system.unreadable", { count: s.businesses_unreadable }) : t("dash.system.upgradesHint")} to="/operator/backups" />
            <Stat label={t("dash.system.mail")} value={s.mail_working ? t("dash.system.working") : s.mail_configured ? t("dash.system.untested") : t("dash.system.notSet")} tone={s.mail_working ? "ok" : "bad"} to="/operator/email" />
            <div className={cx("col-span-2")}>
              <Stat label={t("dash.system.ai")} value={s.ai_has_provider ? `$${s.ai_spend_usd}${cap ? ` / $${cap}` : ""}` : t("dash.system.notSet")} tone={s.ai_cap_reached ? "bad" : undefined}
                hint={!s.ai_has_provider ? t("dash.system.aiNone") : cap ? (s.ai_cap_reached ? t("dash.system.capReached") : t("dash.system.capHint")) : t("dash.system.noCap")} to="/operator/ai" />
            </div>
          </div>
        );
      }}
    </Section>
  );
}
