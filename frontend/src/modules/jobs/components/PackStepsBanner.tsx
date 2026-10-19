import { Link } from "react-router-dom";

import { Card, useTranslation } from "@/sdk";

import { usePackSteps } from "../hooks";

/** A short "getting started" reminder above the jobs while the pack's first steps are not all done (and not hidden). */
export function PackStepsBanner({ companyId }: { companyId: string }) {
  const { t } = useTranslation("jobs");
  const steps = usePackSteps(companyId);
  const list = steps.data ?? [];
  const todo = list.filter((s) => !s.done);
  if (list.length === 0 || todo.length === 0 || list.every((s) => s.hidden)) return null;
  const next = todo[0];
  return (
    <Card className="mb-4">
      <p className="text-sm"><span className="font-medium">{t("garage.start.banner", { done: list.length - todo.length, total: list.length })}</span> {next.title}</p>
      <p className="mt-1 text-sm">{next.to_path && <Link className="font-medium text-brand-strong hover:underline" to={next.to_path}>{t("garage.start.open")}</Link>}{" · "}<Link className="text-muted hover:underline" to="/jobs/settings">{t("garage.start.all")}</Link></p>
    </Card>
  );
}
