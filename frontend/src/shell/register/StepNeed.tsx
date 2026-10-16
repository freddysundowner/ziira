import { Alert, type Edition, Skeleton, useTranslation } from "@/sdk";

import { EditionCards } from "../EditionCards";
import type { FormApi } from "./form";

/** Step 1: which edition. Preselected from the link (?edition= or ?plan=) or the default. */
export function StepNeed({ form, choices, loading, failed, onRetry }: { form: FormApi; choices: readonly Edition[] | undefined; loading: boolean; failed: boolean; onRetry: () => void }) {
  const { t } = useTranslation();
  if (loading) return <Skeleton className="h-48 rounded-xl" />;
  if (failed || !choices) {
    return <Alert tone="bad">{t("edition.loadFailed")} <button type="button" className="font-medium underline" onClick={onRetry}>{t("edition.retry")}</button></Alert>;
  }
  return <EditionCards choices={choices} value={form.values.edition} onChange={(id) => form.set("edition", id)} wide title={false} />;
}
