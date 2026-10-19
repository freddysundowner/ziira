import { Check, Circle } from "lucide-react";
import { Link } from "react-router-dom";

import { GUIDE_FOR_STEP, helpUrl } from "./help";

import { api, Button, Card, EDITION_KEY, progress, toast, unwrap, useCan, useMutation, useQueryClient, useSession, useTranslation, visibleSteps, type Edition, type EditionStep } from "@/sdk";

/** The edition's first steps: what to do to get going, with a tick for each. The owner can hide it; it hides itself when all are done. */
export function Checklist({ edition, done, dismissed, openable }: { edition: Edition; done: readonly string[]; dismissed: boolean; openable: ReadonlySet<string> }) {
  const { t } = useTranslation();
  const { enabledUnits } = useSession();
  const canHide = useCan("units.manage");
  const qc = useQueryClient();
  const steps = visibleSteps(edition, enabledUnits);
  const { done: finished, total, complete } = progress(steps, done);
  const refresh = (mine: unknown) => qc.setQueryData(EDITION_KEY, mine);
  const tick = useMutation({
    meta: { silent: true },
    mutationFn: (v: { id: string; done: boolean }) => unwrap(api.PUT("/api/v1/edition/steps/{step}", { params: { path: { step: v.id } }, body: { done: v.done } })),
    onSuccess: refresh,
    onError: (e) => toast(e.message, "bad"),
  });
  const hide = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PUT("/api/v1/edition/checklist", { body: { dismissed: true } })),
    onSuccess: refresh,
    onError: (e) => toast(e.message, "bad"),
  });
  if (dismissed || steps.length === 0) return null;

  const label = (s: EditionStep, field: "title" | "hint") => t(`edition.steps.${s.id}.${field}`, { defaultValue: s[field] });
  return (
    <Card title={t("edition.checklistTitle", { edition: t(`edition.${edition.id}.title`, { defaultValue: edition.title }) })}
      description={complete ? t("edition.allDone") : t("edition.progress", { done: finished, total })}
      actions={canHide && <Button size="sm" variant="ghost" loading={hide.isPending} onClick={() => hide.mutate()}>{t("edition.hide")}</Button>}>
      <ol className="divide-y divide-line">
        {steps.map((s) => {
          const isDone = done.includes(s.id);
          return (
            <li key={s.id} className="flex items-center gap-3 py-2.5">
              <button type="button" aria-pressed={isDone} aria-label={t(isDone ? "edition.untick" : "edition.tick", { step: label(s, "title") })} disabled={tick.isPending}
                onClick={() => tick.mutate({ id: s.id, done: !isDone })}
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${isDone ? "border-ok bg-ok text-ok-ink" : "border-line text-transparent hover:border-brand"}`}>
                {isDone ? <Check className="h-3.5 w-3.5" /> : <Circle className="h-3.5 w-3.5" />}
              </button>
              <div className="min-w-0 flex-1">
                <p className={`text-sm font-medium ${isDone ? "text-muted line-through" : ""}`}>{label(s, "title")}</p>
                <p className="text-xs text-muted">{label(s, "hint")}</p>
              </div>
              {!isDone && GUIDE_FOR_STEP[s.id] && helpUrl(GUIDE_FOR_STEP[s.id]) && <a href={helpUrl(GUIDE_FOR_STEP[s.id])} target="_blank" rel="noopener noreferrer" className="shrink-0 text-sm text-muted hover:text-brand-strong hover:underline">{t("edition.guide")}</a>}
              {openable.has(s.to) && !isDone && <Link to={s.to} className="shrink-0 text-sm font-medium text-brand-strong hover:underline">{t("edition.open")}</Link>}
            </li>
          );
        })}
      </ol>
    </Card>
  );
}
