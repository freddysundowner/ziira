import { useState } from "react";

import { Alert, api, Button, Checkbox, Field, Modal, Skeleton, Textarea, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation } from "@/sdk";

import { ignoreScopes } from "../plainWords";
import { refreshFindings } from "../refresh";

type Scope = "this" | "branch" | "person" | "everywhere";

/**
 * "Not a problem": close this one, or also tell Ziira that this kind of thing is normal at a branch, for a person, or
 * everywhere (for 30 days or always) so it stops being raised. The rule can be removed later in What Ziira watches.
 */
export default function NotAProblemDialog({ findingId, open, onClose }: { findingId: string; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("intel");
  const qc = useQueryClient();
  const [scope, setScope] = useState<Scope>("this");
  const [forever, setForever] = useState(false);
  const [tune, setTune] = useState(false);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const options = useQuery({
    enabled: open, queryKey: ["intel", "ignore-options", findingId],
    queryFn: () => unwrap(api.GET("/api/v1/intel/findings/{finding_id}/ignore-options", { params: { path: { finding_id: findingId } } })),
  });
  const path = { params: { path: { finding_id: findingId } } };

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => scope === "this"
      ? unwrap(api.POST("/api/v1/intel/findings/{finding_id}/dismiss", { ...path, body: { reason: reason.trim() || t("ignore.defaultReason") } })).then(() => ({ closed: 0 }))
      : unwrap(api.POST("/api/v1/intel/findings/{finding_id}/ignore", { ...path, body: { scope, days: forever ? null : 30, reason: reason.trim() || null, tune } })),
    onSuccess: (result) => {
      refreshFindings(qc, findingId);
      void qc.invalidateQueries({ queryKey: ["intel", "ignore-rules"] });
      toast(result.closed > 0 ? t("ignore.doneMany", { count: result.closed }) : t("ignore.done"), "ok");
      close();
    },
    onError: (e) => { setProblem(e.message); toast(e.message, "bad"); },
  });

  function close() { setScope("this"); setForever(false); setTune(false); setReason(""); setProblem(null); onClose(); }

  const scopes = options.data ? ignoreScopes(options.data) : [];
  const where = (s: Scope) => s === "branch" ? options.data?.branch?.name ?? "" : s === "person" ? options.data?.subject?.label ?? "" : "";
  const choices: Scope[] = ["this", ...scopes];

  return (
    <Modal open={open} onClose={close} title={t("ignore.title")}
      footer={<><Button variant="secondary" onClick={close}>{t("cancel")}</Button><Button loading={save.isPending} disabled={!options.data && !options.error} onClick={() => save.mutate()}>{t("ignore.confirm")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("ignore.hint")}</p>
        {options.isLoading ? <Skeleton className="h-24 w-full" /> : (
          <fieldset className="space-y-2">
            <legend className="sr-only">{t("ignore.what")}</legend>
            {choices.map((s) => (
              <label key={s} className="flex cursor-pointer items-start gap-3 rounded-lg border border-line p-3 text-sm has-[:checked]:border-brand has-[:checked]:bg-brand-soft">
                <input type="radio" name="ignore-scope" className="mt-0.5 h-4 w-4 accent-brand" checked={scope === s} onChange={() => setScope(s)} />
                <span>{t(`ignore.scope.${s}`, { where: where(s) })}</span>
              </label>
            ))}
          </fieldset>
        )}
        {scope !== "this" && (
          <fieldset className="flex flex-wrap gap-4 text-sm">
            <legend className="sr-only">{t("ignore.howLong")}</legend>
            <label className="flex items-center gap-2"><input type="radio" name="ignore-time" className="accent-brand" checked={!forever} onChange={() => setForever(false)} />{t("ignore.thirtyDays")}</label>
            <label className="flex items-center gap-2"><input type="radio" name="ignore-time" className="accent-brand" checked={forever} onChange={() => setForever(true)} />{t("ignore.always")}</label>
          </fieldset>
        )}
        {scope !== "this" && options.data?.tunable && <Checkbox label={t("ignore.tune")} checked={tune} onChange={(e) => setTune(e.target.checked)} />}
        <Field label={t("ignore.reason")}><Textarea rows={2} maxLength={2000} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        {scope !== "this" && <p className="text-xs text-muted">{t("ignore.undo")}</p>}
        {(problem || options.error) && <Alert tone="bad">{problem ?? options.error?.message}</Alert>}
      </div>
    </Modal>
  );
}
