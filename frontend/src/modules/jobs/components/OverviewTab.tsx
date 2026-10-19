import { Card, DetailList, useTranslation } from "@/sdk";

import type { Job } from "../types";
import { ChecklistCard } from "./ChecklistCard";
import { TasksCard } from "./TasksCard";

/** What is wrong, the item's condition when it came in, the checks and the tasks. */
export function OverviewTab({ job, editable }: { job: Job; editable: boolean }) {
  const { t } = useTranslation("jobs");
  return (
    <div className="space-y-4">
      <Card title={t("overview.title")}>
        <DetailList items={[
          { label: t("receive.details"), value: job.description ? <span className="whitespace-pre-line">{job.description}</span> : <span className="text-muted">{t("overview.none")}</span> },
          { label: t("receive.condition"), value: job.condition_notes ? <span className="whitespace-pre-line">{job.condition_notes}</span> : <span className="text-muted">{t("overview.none")}</span> },
        ]} />
      </Card>
      <ChecklistCard job={job} editable={editable} />
      <TasksCard job={job} editable={editable} />
    </div>
  );
}
