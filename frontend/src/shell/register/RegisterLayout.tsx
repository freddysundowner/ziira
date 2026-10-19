import { Check } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { BrandWord, cx, useTranslation } from "@/sdk";

import { BrandPanel } from "../BrandPanel";
import { STEPS, type StepId } from "./state";

/**
 * The whole-page frame of sign-up: a progress rail on the left (a bar on a phone), the step in the middle at full width,
 * and a panel on the right (under the step on a phone) that reflects the choices.
 */
export function RegisterLayout({ step, done, reachable, onGo, side, children }: {
  step: StepId | null;
  /** Steps whose answers are complete (they get a check mark). */
  done: ReadonlySet<StepId>;
  /** Steps the person may jump to. */
  reachable: ReadonlySet<StepId>;
  onGo: (step: StepId) => void;
  /** The right-hand panel; none on the "creating" page. */
  side: ReactNode | null;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const index = step ? STEPS.indexOf(step) : STEPS.length - 1;
  return (
    <div className="grid min-h-screen bg-bg lg:grid-cols-[minmax(380px,0.9fr)_minmax(0,1.6fr)]">
    <BrandPanel className="max-lg:hidden lg:sticky lg:top-0 lg:h-screen" />
    <div className="flex min-w-0 flex-col">
      <header className="flex items-center justify-between gap-4 border-b border-line bg-surface px-4 py-4 sm:px-8 lg:justify-end">
        <Link to="/" className="flex items-center gap-2.5 lg:hidden" aria-label={t("appName")}>
          <BrandWord className="h-9" />
        </Link>
        <Link to="/" className="text-sm font-medium text-brand-strong hover:underline">{t("signup.haveAccount")}</Link>
      </header>

      {step && (
        <nav aria-label={t("signup.progress")} className="border-b border-line bg-surface px-4 py-3 lg:hidden">
          <p className="mb-2 text-sm font-medium">{t("signup.stepOf", { n: index + 1, total: STEPS.length, title: t(`signup.steps.${STEPS[index]}`) })}</p>
          <div className="flex gap-1.5" aria-hidden>
            {STEPS.map((s, i) => <span key={s} className={cx("h-1.5 flex-1 rounded-full", i <= index ? "bg-brand-gradient" : "bg-line")} />)}
          </div>
        </nav>
      )}

      <div className={cx("grid flex-1", side ? "lg:grid-cols-[220px_minmax(0,1fr)] 2xl:grid-cols-[220px_minmax(0,1fr)_340px]" : "lg:grid-cols-[220px_minmax(0,1fr)]")}>
        {step ? (
          <nav aria-label={t("signup.progress")} className="hidden border-r border-line bg-surface p-6 lg:block">
            <ol className="space-y-1">
              {STEPS.map((s, i) => {
                const complete = done.has(s) && s !== step;
                const current = s === step;
                return (
                  <li key={s}>
                    <button
                      type="button" disabled={!reachable.has(s) || current} aria-current={current ? "step" : undefined} onClick={() => onGo(s)}
                      className={cx("flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors enabled:hover:bg-sunken disabled:cursor-default", current && "bg-brand-soft font-semibold text-brand-strong")}
                    >
                      <span className={cx("flex h-7 w-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold", complete ? "border-brand bg-brand text-brand-ink" : current ? "border-brand-strong text-brand-strong" : "border-line text-muted")}>
                        {complete ? <Check className="h-4 w-4" aria-hidden /> : i + 1}
                        {complete && <span className="sr-only">{t("signup.done")}</span>}
                      </span>
                      <span className={cx(!current && !complete && "text-muted")}>{t(`signup.steps.${s}`)}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>
        ) : <div className="hidden lg:block" />}

        <main className="min-w-0 px-4 py-8 sm:px-8 lg:px-12 lg:py-12">{children}</main>

        {side && <aside className="hidden border-line bg-surface p-8 2xl:col-span-1 2xl:block 2xl:border-l">{side}</aside>}
      </div>
    </div>
    </div>
  );
}
