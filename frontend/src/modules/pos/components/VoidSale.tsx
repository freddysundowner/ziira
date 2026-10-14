import { type FormEvent, useState } from "react";

import { api, Button, Field, Modal, orNull, Select, Textarea, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { useReasons } from "../hooks";

/** Cancels a sale while its till is still open: payments, stock and books are reversed. Asks for a reason first. */
export function VoidSale({ saleId, number, open, onClose }: { saleId: string; number: string; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const reasons = useReasons("void", open);
  const [reasonId, setReasonId] = useState("");
  const [note, setNote] = useState("");
  const reason = reasons.data?.find((r) => r.id === reasonId);

  const voidSale = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/pos/sales/{sale_id}/void", { params: { path: { sale_id: saleId } }, body: { reason_code_id: reasonId, note: orNull(note) } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["pos-sale", saleId] });
      void qc.invalidateQueries({ queryKey: ["pos-sales"] });
      toast(t("voidDone", { number }), "ok");
      setReasonId(""); setNote(""); onClose();
    },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); voidSale.mutate(); };

  return (
    <Modal open={open} onClose={onClose} title={t("voidTitle", { number })} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="void-sale" variant="danger" loading={voidSale.isPending} disabled={!reasonId || (reason?.requires_note && !note.trim())}>{t("voidSale")}</Button></>}>
      <form id="void-sale" onSubmit={submit} className="space-y-4">
        <p className="text-sm text-muted">{t("voidWarning")}</p>
        <Field label={t("reason")} required>
          <Select value={reasonId} onChange={(e) => setReasonId(e.target.value)} required autoFocus>
            <option value="">{t("choose")}</option>
            {(reasons.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </Select>
        </Field>
        <Field label={t("note")} required={reason?.requires_note}><Textarea rows={2} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </form>
    </Modal>
  );
}
