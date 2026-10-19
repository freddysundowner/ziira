import { Check, Circle } from "lucide-react";

import { Alert, Attachments, Card, useTranslation } from "@/sdk";

import type { Job } from "../types";

/** The photos of a job (intake, damage, odometer, progress, the old part ...) and the photos its kind of job still needs. */
export function PhotosTab({ job }: { job: Job }) {
  const { t } = useTranslation("jobs");
  const missing = job.photos.filter((p) => !p.ok);
  return (
    <div className="space-y-4">
      {job.photos.length > 0 && (
        <Card title={t("garage.photos.required")} description={t("garage.photos.requiredHint")}>
          <ul className="divide-y divide-line text-sm">
            {job.photos.map((p) => (
              <li key={`${p.category}-${p.before}`} className="flex items-center justify-between gap-3 py-2">
                <span className="inline-flex items-center gap-2">
                  {p.ok ? <Check className="h-4 w-4 text-ok" aria-hidden /> : <Circle className="h-4 w-4 text-muted" aria-hidden />}
                  <span className={p.ok ? "text-muted" : "font-medium"}>{p.name}</span>
                </span>
                <span className="tnum text-xs text-muted">{t("garage.photos.count", { have: p.have, need: p.minimum })} · {t("garage.photos.before", { stage: t(`garage.photos.stage.${p.before}`) })}</span>
              </li>
            ))}
          </ul>
          {missing.length > 0 && <Alert tone="warn" className="mt-3">{t("garage.photos.missing")}</Alert>}
        </Card>
      )}
      <Attachments entityType="jobs.job" entityId={job.id} title={t("garage.photos.title")} />
      <p className="text-xs text-muted">{t("garage.photos.shareHint")}</p>
    </div>
  );
}
