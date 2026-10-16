import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, ConfirmDialog, ErrorState, formatDate, Skeleton, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";
import { KEYS } from "./api";

/** A page's history: every saved version, a text comparison of any two, and restore (which makes a new version). */
export function VersionsPanel({ pageId, current, onRestored }: { pageId: string; current: number; onRestored: () => void }) {
  const { t } = useTranslation("operator");
  const queryClient = useQueryClient();
  const [compare, setCompare] = useState<number | null>(null);
  const [restoring, setRestoring] = useState<number | null>(null);
  const versions = useQuery({ queryKey: KEYS.versions(pageId), queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/site/pages/{page_id}/versions", { params: { path: { page_id: pageId } } })) });
  const diff = useQuery({
    queryKey: ["operator", "site", "diff", pageId, compare, current],
    enabled: compare !== null && compare !== current,
    queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/site/pages/{page_id}/diff", { params: { path: { page_id: pageId }, query: { older: compare as number, newer: current } } })),
  });
  const restore = useChange(
    (version: number) => opUnwrap(opApi.POST("/api/v1/operator/site/pages/{page_id}/versions/{version}/restore", { params: { path: { page_id: pageId, version } } })),
    {
      onSuccess: (_page, version) => {
        toast(t("website.pages.restored", { version }), "ok");
        setRestoring(null);
        void queryClient.invalidateQueries({ queryKey: ["operator", "site"] });
        onRestored();
      },
      onError: (e) => { toast(e.message, "bad"); setRestoring(null); },
    },
  );

  if (versions.isPending) return <Skeleton className="h-32 w-full" />;
  if (versions.isError) return <ErrorState message={versions.error.message} onRetry={() => void versions.refetch()} />;
  return (
    <div className="space-y-3">
      <ul className="divide-y divide-line rounded-lg border border-line">
        {versions.data.map((v) => (
          <li key={v.version} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
            <div>
              <p className="font-medium">{t("website.pages.version", { version: v.version })} {v.version === current && <Badge tone="brand">{t("website.pages.currentVersion")}</Badge>}</p>
              <p className="text-xs text-muted">{formatDate(v.created_at, true)} - {v.created_by ?? "-"}{v.note ? ` - ${v.note}` : ""}</p>
            </div>
            {v.version !== current && (
              <div className="flex gap-2">
                <Button size="sm" variant={compare === v.version ? "primary" : "secondary"} onClick={() => setCompare(compare === v.version ? null : v.version)}>{t("website.pages.compare")}</Button>
                <Button size="sm" variant="secondary" onClick={() => setRestoring(v.version)}>{t("website.pages.restore")}</Button>
              </div>
            )}
          </li>
        ))}
      </ul>
      {compare !== null && (
        diff.isPending ? <Skeleton className="h-24 w-full" /> :
        diff.isError ? <Alert tone="bad">{diff.error.message}</Alert> :
        <div>
          <p className="mb-1 text-xs text-muted">{t("website.pages.diffSummary", { older: compare, newer: current, added: diff.data.added, removed: diff.data.removed })}</p>
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-sunken p-3 text-xs">
            {diff.data.diff.split("\n").map((line, i) => (
              <span key={i} className={line.startsWith("+") && !line.startsWith("+++") ? "block text-ok" : line.startsWith("-") && !line.startsWith("---") ? "block text-bad" : "block text-muted"}>{line || " "}</span>
            ))}
          </pre>
        </div>
      )}
      <ConfirmDialog open={restoring !== null} onClose={() => setRestoring(null)} busy={restore.isPending} title={t("website.pages.restoreTitle")}
        message={t("website.pages.restoreMessage", { version: restoring })} confirmLabel={t("website.pages.restore")}
        onConfirm={() => restoring !== null && restore.mutate(restoring)} />
    </div>
  );
}
