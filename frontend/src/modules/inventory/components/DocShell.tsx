import type { ReactNode } from "react";

import { ErrorState, Skeleton, useTranslation } from "@/sdk";

/** Loading and error frame for a document's page: shows the skeleton or the retry, else the page. */
export function DocShell({ loading, error, onRetry, children }: { loading: boolean; error?: string | null; onRetry: () => void; children: ReactNode }) {
  const { t } = useTranslation("inventory");
  if (error) return <ErrorState title={t("notFound")} message={error} onRetry={onRetry} />;
  if (loading) return <Skeleton className="h-40 w-full" />;
  return <>{children}</>;
}
