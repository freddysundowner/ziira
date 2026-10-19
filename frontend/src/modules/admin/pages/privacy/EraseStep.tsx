import { Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  api, Alert, Button, ConfirmDialog, ErrorText, Field, humanise, Input, Textarea, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import ErasureResults from "./ErasureResults";
import {
  asRetention, countBySource, erasureOf, type Found, isFinished, type PrivacyRequest, reasonIsEnough, recordIdsFor, rulesForSources, subjectMatches,
} from "./model";

/** Step 3 (erasure requests only): show what will change and what must stay, then erase after typing the subject. */
export default function EraseStep({ request, found, confirmed, userName, canEdit }: {
  request: PrivacyRequest; found: Found[]; confirmed: ReadonlySet<string>; userName: (id: string | null) => string; canEdit: boolean;
}) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");
  const [asking, setAsking] = useState(false);

  const selected = found.filter((f) => f.match === "exact" || confirmed.has(f.record_id));
  const perUnit = countBySource(selected);
  const retention = useQuery({
    queryKey: ["privacy-retention", request.company_id],
    queryFn: async () => asRetention(await unwrap(api.GET("/api/v1/privacy/retention", { params: { query: { company_id: request.company_id } } }))),
  });
  // The setting needs another permission; if it cannot be read the screen just describes both cases.
  const settings = useQuery({
    queryKey: ["company-settings", request.company_id], retry: false, meta: { silent: true },
    queryFn: () => unwrap(api.GET("/api/v1/companies/{company_id}/settings", { params: { path: { company_id: request.company_id } } })),
  });
  const needsApproval = settings.data?.privacy_erasure_needs_approval;
  const rules = rulesForSources(retention.data?.rules ?? [], perUnit.map((u) => u.source));

  const erase = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/privacy/requests/{request_id}/erase", {
      params: { path: { request_id: request.id } }, body: { confirm_subject: typed, reason: reason.trim(), record_ids: recordIdsFor(found, confirmed) },
    })),
    onSuccess: (r) => {
      qc.setQueryData(["privacy-request", request.id], r);
      void qc.invalidateQueries({ queryKey: ["privacy-requests"] });
      toast(r.awaiting_approval ? t("dsr.erase.sentForApproval") : t("dsr.erase.done"), "ok");
      setAsking(false);
      setTyped("");
    },
    onError: (e) => { setAsking(false); toast((e as Error).message, "bad"); },
  });

  const erasure = erasureOf(request.outcome);
  if (erasure) return <ErasureResults erasure={erasure} userName={userName} />;
  if (isFinished(request)) return <Alert tone="info">{t("dsr.erase.notRun")}</Alert>;

  if (request.awaiting_approval) {
    return (
      <div className="space-y-3">
        <Alert tone="warn">{t("dsr.erase.waiting")}</Alert>
        <p className="text-sm text-muted">{t("dsr.erase.waitingHelp")}</p>
        <Link className="text-sm font-medium text-brand-strong hover:underline" to="/admin/approvals">{t("dsr.erase.openApprovals")}</Link>
      </div>
    );
  }

  const ready = canEdit && selected.length > 0 && subjectMatches(typed, request.subject) && reasonIsEnough(reason);
  return (
    <div className="space-y-4">
      <Alert tone="bad"><strong>{t("dsr.erase.irreversible")}</strong> {t("dsr.erase.irreversibleHelp")}</Alert>

      <div>
        <h3 className="mb-1 text-sm font-semibold">{t("dsr.erase.willChange")}</h3>
        {perUnit.length === 0
          ? <p className="text-sm text-muted">{t("dsr.erase.nothingSelected")}</p>
          : <ul className="list-inside list-disc text-sm">{perUnit.map((u) => <li key={u.source}>{t("dsr.erase.unitCount", { unit: t(`dsr.source.${u.source}`, { defaultValue: humanise(u.source) }), count: u.count })}</li>)}</ul>}
        <p className="mt-1 text-xs text-muted">{t("dsr.erase.willChangeHint")}</p>
      </div>

      <div>
        <h3 className="mb-1 text-sm font-semibold">{t("dsr.erase.mayBeKept")}</h3>
        {retention.error ? <ErrorText>{retention.error.message}</ErrorText>
          : rules.length === 0 ? <p className="text-sm text-muted">{retention.isLoading ? t("dsr.loading") : t("dsr.erase.noRules")}</p>
          : (
            <ul className="space-y-1.5 text-sm">
              {rules.map((r) => (
                <li key={`${r.unit}:${r.code}`} className="rounded-lg bg-sunken px-3 py-2">
                  <span className="font-medium">{t(`dsr.source.${r.unit}`, { defaultValue: humanise(r.unit) })}: {r.what}</span>
                  <span className="block text-xs text-muted">{r.basis} · {r.period}</span>
                </li>
              ))}
            </ul>
          )}
        <p className="mt-1 text-xs text-muted">{t("dsr.erase.keptHint")}</p>
      </div>

      <Alert tone="info">
        {needsApproval === undefined ? t("dsr.erase.approvalUnknown") : needsApproval ? t("dsr.erase.approvalOn") : t("dsr.erase.approvalOff")}
      </Alert>

      {canEdit && (
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (ready) setAsking(true); }}>
          <Field label={t("dsr.erase.typeSubject", { subject: request.subject_masked })} hint={t("dsr.erase.typeSubjectHint")}>
            <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" maxLength={200} />
          </Field>
          <Field label={t("dsr.erase.reason")} hint={t("dsr.erase.reasonHint")}>
            <Textarea rows={2} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <ErrorText>{erase.error?.message}</ErrorText>
          <Button type="submit" variant="danger" disabled={!ready}><Trash2 className="h-4 w-4" />{needsApproval === false ? t("dsr.erase.button") : t("dsr.erase.buttonApproval")}</Button>
        </form>
      )}
      <ConfirmDialog open={asking} onClose={() => setAsking(false)} danger busy={erase.isPending} title={t("dsr.erase.confirmTitle")}
        confirmLabel={t("dsr.erase.confirmButton")} message={t("dsr.erase.confirmMessage", { count: selected.length })} onConfirm={() => erase.mutate()} />
    </div>
  );
}
