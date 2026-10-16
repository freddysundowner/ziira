import { ArrowRight, CheckCircle2, Circle } from "lucide-react";
import { Link } from "react-router-dom";

import { Badge, Button, Card, cx, ErrorState, Skeleton, useTranslation } from "@/sdk";

import { canAct, nextStep, setupProgress, visibleSteps } from "../helpers/setup";
import { useOperatorMe } from "../me";
import { useSetup } from "../shell/data";
import { useAvailability } from "../pages/website/api";

/**
 * "Where do I find ...?": the first-time set-up in order, each step done or not from the platform's real state, with a link
 * to the screen where it is done. The answer to where each setting lives, for a new owner and for anyone who forgot.
 */
export function SetupChecklist({ full = false }: { full?: boolean }) {
  const { t } = useTranslation("operator");
  const setup = useSetup();
  const me = useOperatorMe();
  const site = useAvailability();
  if (setup.isPending) return <Card><Skeleton className="h-32 w-full" /></Card>;
  if (setup.isError) return <ErrorState title={t("setup.loadFailed")} message={setup.error.message} onRetry={() => void setup.refetch()} />;
  const permissions = me.data?.permissions ?? [];
  const steps = visibleSteps(setup.data.items, site.data && !site.data.available ? ["website"] : []);
  const progress = setupProgress(steps);
  if (!full && progress.complete) return null;
  const next = nextStep(steps);
  const numbered = steps.map((s, i) => ({ ...s, number: i + 1 }));
  return (
    <Card title={t("setup.title")} description={progress.complete ? t("setup.allDone") : t("setup.intro")}
      actions={<><Badge tone={progress.complete ? "ok" : "brand"}>{t("setup.progress", { done: progress.done, total: progress.total })}</Badge>
        {next && canAct(next, permissions) && <Link to={next.to}><Button size="sm">{t("setup.start")} <ArrowRight className="h-3.5 w-3.5" /></Button></Link>}</>}>
      <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-sunken" role="progressbar" aria-valuemin={0} aria-valuemax={progress.total} aria-valuenow={progress.done} aria-label={t("setup.title")}>
        <div className="h-full rounded-full bg-brand transition-[width] motion-reduce:transition-none" style={{ width: `${progress.total ? (progress.done / progress.total) * 100 : 0}%` }} />
      </div>
      <ol className={cx("grid gap-2", full ? "lg:grid-cols-2" : "xl:grid-cols-2")}>
        {numbered.map((s) => (
          <li key={s.key} className="flex items-start gap-3 rounded-lg border border-line p-3">
            {s.done ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-ok" aria-label={t("setup.done")} /> : <Circle className="mt-0.5 h-5 w-5 shrink-0 text-muted" aria-label={t("setup.todo")} />}
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{s.number}. {t(`setup.items.${s.key}.title`)}{s.optional && <span className="ml-2 text-xs font-normal text-muted">{t("setup.optional")}</span>}</p>
              <p className="mt-0.5 text-xs text-muted">{t(`setup.items.${s.key}.text`)}{s.key === "registration" && s.detail ? ` ${t("setup.currentMode", { mode: t(`psettings.registration.${s.detail}`, s.detail) })}` : ""}</p>
              {canAct(s, permissions)
                ? <Link to={s.to} className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-brand-strong hover:underline">{t(`setup.items.${s.key}.link`)} <ArrowRight className="h-3 w-3" aria-hidden /></Link>
                : <p className="mt-1 text-xs text-muted">{t("setup.noAccess")}</p>}
            </div>
          </li>
        ))}
      </ol>
    </Card>
  );
}
