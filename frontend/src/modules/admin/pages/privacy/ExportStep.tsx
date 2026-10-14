import { Download } from "lucide-react";

import { api, Alert, Button, formatDate, toast, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { saveDownload } from "./download";
import { exportFileName, exportsOf, type PrivacyRequest } from "./model";

/** Step 2: take the JSON bundle of what is held. Every export is written to the audit log by the server. */
export default function ExportStep({ request, recordIds, count, canEdit }: {
  request: PrivacyRequest; recordIds: string[] | undefined; count: number; canEdit: boolean;
}) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const download = useMutation({
    meta: { silent: true },
    mutationFn: () => saveDownload(
      api.POST("/api/v1/privacy/requests/{request_id}/export", { params: { path: { request_id: request.id } }, body: { record_ids: recordIds }, parseAs: "blob" }),
      exportFileName(request.number)),
    onSuccess: () => { toast(t("dsr.export.saved"), "ok"); void qc.invalidateQueries({ queryKey: ["privacy-request", request.id] }); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const history = exportsOf(request.outcome);
  const erased = request.request_type === "erasure" && (request.status === "completed" || request.status === "refused");

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted">{request.request_type === "erasure" ? t("dsr.export.introErasure") : t("dsr.export.intro")}</p>
      <Alert tone="info">{t("dsr.export.logged")}</Alert>
      {erased ? <Alert tone="warn">{t("dsr.export.gone")}</Alert> : canEdit && (
        <div className="flex flex-wrap items-center gap-3">
          <Button loading={download.isPending} disabled={count === 0} onClick={() => download.mutate()}><Download className="h-4 w-4" />{t("dsr.export.button")}</Button>
          <span className="text-sm text-muted">{t("dsr.export.willInclude", { count })}</span>
        </div>
      )}
      {history.length > 0 && (
        <div>
          <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">{t("dsr.export.history")}</h3>
          <ul className="space-y-0.5 text-sm">{history.map((h, i) => <li key={i}>{t("dsr.export.entry", { date: formatDate(h.at, true), count: h.records })}</li>)}</ul>
        </div>
      )}
    </div>
  );
}
