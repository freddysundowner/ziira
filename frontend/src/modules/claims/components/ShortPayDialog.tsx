import { useEffect, useState } from "react";

import { api, Button, Field, Modal, money, Select, Textarea, unwrap, useTranslation } from "@/sdk";

import { useClaimsMutation } from "../hooks";
import type { ShortPay } from "../types";

/** What to do with a payment that came up short: charge the customer, argue it with the payer, or accept the loss. */
export function ShortPayDialog({ shortPay, currency, onClose }: { shortPay: ShortPay | null; currency: string | undefined; onClose: () => void }) {
  const { t } = useTranslation("claims");
  const [choice, setChoice] = useState("recharge");
  const [note, setNote] = useState("");
  const [tried, setTried] = useState(false);
  useEffect(() => { if (shortPay) { setChoice("recharge"); setNote(""); setTried(false); } }, [shortPay]);
  const save = useClaimsMutation(() => unwrap(api.POST("/api/v1/claims/short-pays/{short_pay_id}/resolve", { params: { path: { short_pay_id: shortPay?.id ?? "" } }, body: { resolution: choice as "recharge" | "accept" | "dispute", note: note.trim() || null } })),
    { done: t("shortPay.done"), onDone: onClose });
  const needNote = choice !== "recharge";
  return (
    <Modal open={shortPay !== null} onClose={onClose} title={t("shortPay.title")} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={save.isPending} onClick={() => { setTried(true); if (!needNote || note.trim()) save.mutate(undefined); }}>{t("common.save")}</Button></>}>
      <div className="space-y-4">
        <p className="text-sm">{t("shortPay.summary", { expected: money(shortPay?.expected, currency), paid: money(shortPay?.paid, currency), difference: money(shortPay?.difference, currency) })}</p>
        <Field label={t("shortPay.what")}>
          <Select value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="recharge">{t("shortPay.recharge")}</option>
            <option value="dispute">{t("shortPay.dispute")}</option>
            <option value="accept">{t("shortPay.accept")}</option>
          </Select>
        </Field>
        <p className="text-xs text-muted">{t(`shortPay.hint.${choice}`)}</p>
        <Field label={t("shortPay.note")} required={needNote} error={tried && needNote && !note.trim() ? t("shortPay.noteNeeded") : null}><Textarea maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
