import { type ReactNode, useState } from "react";
import { Link } from "react-router-dom";

import { Alert, api, Button, Field, Modal, Textarea, toast, unwrap, useCan, useMutation, useQueryClient, useTranslation } from "@/sdk";
import type { Schemas } from "@/sdk";

import PersonPicker from "./PersonPicker";

type Detail = Schemas["FindingDetailOut"];
export type DialogKind = "acknowledge" | "explain" | "resolve" | "dismiss" | "assign" | "ask";

/** One modal for every action on a finding; which fields it shows depends on the action. */
export default function FindingDialog({ kind, finding, onClose }: { kind: DialogKind | null; finding: Detail; onClose: () => void }) {
  const { t } = useTranslation("intel");
  const qc = useQueryClient();
  const canSettings = useCan("settings.manage");
  const [text, setText] = useState("");
  const [person, setPerson] = useState(finding.owner_user_id ?? "");
  const [problem, setProblem] = useState<string | null>(null);
  const path = { params: { path: { finding_id: finding.id } } };

  const run = useMutation({
    meta: { silent: true },
    mutationFn: (): Promise<Detail> => {
      switch (kind) {
        case "acknowledge": return unwrap(api.POST("/api/v1/intel/findings/{finding_id}/acknowledge", { ...path, body: { note: text.trim() || null } }));
        case "explain": return unwrap(api.POST("/api/v1/intel/findings/{finding_id}/explain", { ...path, body: { note: text.trim() } }));
        case "resolve": return unwrap(api.POST("/api/v1/intel/findings/{finding_id}/resolve", { ...path, body: { note: text.trim() || null } }));
        case "dismiss": return unwrap(api.POST("/api/v1/intel/findings/{finding_id}/dismiss", { ...path, body: { reason: text.trim() } }));
        case "assign": return unwrap(api.POST("/api/v1/intel/findings/{finding_id}/assign", { ...path, body: { user_id: person || null } }));
        default: return unwrap(api.POST("/api/v1/intel/findings/{finding_id}/ask", { ...path, body: { user_id: person, message: text.trim() } }));
      }
    },
    onSuccess: (updated) => {
      qc.setQueryData(["intel", "finding", finding.id], updated);
      void qc.invalidateQueries({ queryKey: ["intel", "findings"] });
      void qc.invalidateQueries({ queryKey: ["intel", "summary"] });
      toast(t(`done.${kind}`), "ok");
      close();
    },
    onError: (e) => { setProblem(e.message); toast(e.message, "bad"); },
  });

  function close() { setText(""); setProblem(null); setPerson(finding.owner_user_id ?? ""); onClose(); }
  if (!kind) return null;

  const needsText = kind === "explain" || kind === "dismiss";
  const needsPerson = kind === "assign" || kind === "ask";
  const ready = (!needsText || text.trim().length > 0) && (kind !== "ask" || person !== "");
  const askRefused = kind === "ask" && !!problem && /intel_action_level/.test(problem);
  let fields: ReactNode = null;
  if (needsPerson) {
    fields = (
      <Field label={t("person")} hint={t(kind === "ask" ? "askPersonHint" : "assignPersonHint")}>
        <PersonPicker value={person} onChange={setPerson} clearable={kind === "assign"} />
      </Field>
    );
  }

  return (
    <Modal open onClose={close} title={t(`dialog.${kind}`)}
      footer={
        <>
          <Button variant="secondary" onClick={close}>{t("cancel")}</Button>
          <Button variant={kind === "dismiss" ? "danger" : "primary"} loading={run.isPending} disabled={!ready} form="finding-action" type="submit">{t(`confirm.${kind}`)}</Button>
        </>
      }>
      <form id="finding-action" className="space-y-4" onSubmit={(e) => { e.preventDefault(); if (ready) run.mutate(); }}>
        <p className="text-sm text-muted">{t(`dialogHint.${kind}`)}</p>
        {fields}
        {kind !== "assign" && (
          <Field label={t(`noteLabel.${kind}`)} required={needsText}>
            <Textarea rows={4} maxLength={kind === "ask" ? 1000 : 2000} value={text} onChange={(e) => setText(e.target.value)} />
          </Field>
        )}
        {problem && (
          <Alert tone="bad">
            {askRefused ? t("askNeedsLevel") : problem}
            {askRefused && canSettings && <> <Link className="underline" to="/admin/settings">{t("openSettings")}</Link></>}
          </Alert>
        )}
      </form>
    </Modal>
  );
}
