import { type FormEvent } from "react";

import {
  api, Alert, Button, Field, Modal, NumberInput, orNull, Select, Textarea, toast, unwrap, useFormState, useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import { useMoney, useReasons } from "../hooks";
import { variancePreview } from "../lib";

/** Counts the drawer and closes the till. A difference needs a reason; the server decides whether the count is accepted. */
export function CloseTill({ tillId, expectedCash, open, onClose }: { tillId: string; expectedCash: string; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const m = useMoney();
  const reasons = useReasons("till_variance", open);
  const f = useFormState({ counted_cash: "", reason_code_id: "", note: "" });
  const diff = variancePreview(expectedCash, f.values.counted_cash);
  const reason = reasons.data?.find((r) => r.id === f.values.reason_code_id);

  const close = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/pos/tills/{till_id}/close", { params: { path: { till_id: tillId } }, body: {
      counted_cash: f.values.counted_cash, reason_code_id: diff ? f.values.reason_code_id || null : null, note: orNull(f.values.note) } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["pos-till", tillId] });
      void qc.invalidateQueries({ queryKey: ["pos-till-report", tillId] });
      void qc.invalidateQueries({ queryKey: ["pos-tills"] });
      toast(t("tillClosed"), "ok"); f.reset(); onClose();
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); close.mutate(); };

  return (
    <Modal open={open} onClose={onClose} title={t("closeTill")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="close-till" loading={close.isPending} disabled={diff === null || Boolean(diff && !f.values.reason_code_id)}>{t("closeTill")}</Button></>}>
      <form id="close-till" onSubmit={submit} className="space-y-4">
        <p className="text-sm text-muted">{t("closeTillHint")}</p>
        <Field label={t("countedCash")} required error={f.error("counted_cash")}><NumberInput {...f.bind("counted_cash")} onChange={(v) => f.set("counted_cash", v)} autoFocus required /></Field>
        {diff !== null && (diff === 0
          ? <Alert tone="ok">{t("noDifference")}</Alert>
          : <Alert tone="warn">{t(diff < 0 ? "short" : "over", { amount: m(String(Math.abs(diff))) })}</Alert>)}
        {Boolean(diff) && (
          <>
            <Field label={t("reason")} required error={f.error("reason_code_id")}>
              <Select {...f.bind("reason_code_id")} required>
                <option value="">{t("choose")}</option>
                {(reasons.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
              </Select>
            </Field>
            <Field label={t("note")} required={reason?.requires_note} error={f.error("note")}><Textarea rows={2} maxLength={500} {...f.bind("note")} /></Field>
          </>
        )}
      </form>
    </Modal>
  );
}
