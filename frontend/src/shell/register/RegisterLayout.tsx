import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { BrandWord, useTranslation } from "@/sdk";

import { STEPS, type StepId } from "./state";

/**
 * The whole-page frame of sign-up: the logo and a way back to sign-in, one thin progress line under them, and the question in a
 * single centred column. Nothing else (no step list, no side panels).
 */
export function RegisterLayout({ step, children }: {
  step: StepId | null;
  /** The numbered answers are kept by the parent; only the position matters here. */
  done?: ReadonlySet<StepId>;
  reachable?: ReadonlySet<StepId>;
  onGo?: (step: StepId) => void;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const index = step ? STEPS.indexOf(step) : STEPS.length - 1;
  const percent = step ? Math.round(((index + 1) / STEPS.length) * 100) : 100;
  return (
    <div className="flex min-h-screen flex-col bg-bg">
      <header className="flex items-center justify-between gap-4 bg-surface px-4 py-4 sm:px-8">
        <Link to="/" className="flex items-center gap-2.5" aria-label={t("appName")}>
          <BrandWord className="h-9" />
        </Link>
        <Link to="/" className="text-sm font-medium text-brand-strong hover:underline">{t("signup.haveAccount")}</Link>
      </header>
      <div
        role="progressbar" aria-label={t("signup.progress")} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}
        aria-valuetext={step ? t("signup.stepOf", { n: index + 1, total: STEPS.length, title: t(`signup.steps.${STEPS[index]}`) }) : undefined}
        className="h-1 w-full bg-line"
      >
        <div className="h-full rounded-r-full bg-brand-gradient transition-[width] duration-300" style={{ width: `${percent}%` }} />
      </div>
      <main className="mx-auto w-full min-w-0 flex-1 px-4 py-8 sm:px-8 lg:w-4/5 lg:max-w-none lg:px-0 lg:py-10">{children}</main>
    </div>
  );
}
