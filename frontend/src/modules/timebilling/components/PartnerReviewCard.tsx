import { useState } from "react";

import { Alert, api, Badge, Button, Card, Field, Modal, Textarea, toast, unwrap, useCan, useMutation, useTranslation } from "@/sdk";

import { useRefresh } from "../hooks";
import type { Review } from "../types";

const TONE = { none: "neutral", requested: "warn", approved: "ok", changes_requested: "bad" } as const;

/** Partner review: the person who built the review asks a partner to look at it; the partner approves or sends it back with a note. */
export function PartnerReviewCard({ review }: { review: Review }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const partner = useCan("time.partner");
  const canBill = useCan("time.bill");
  const [sending, setSending] = useState(false);
  const [note, setNote] = useState("");
  const path = { batch_id: review.id };
  const ask = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/timebilling/invoice-reviews/{batch_id}/request-review", { params: { path } })),
    onSuccess: () => { toast(t("partner.asked"), "ok"); void refresh(); },
  });
  const decide = useMutation({
    mutationFn: (approve: boolean) => unwrap(api.POST("/api/v1/timebilling/invoice-reviews/{batch_id}/review", { params: { path }, body: { approve, note: approve ? null : note.trim() } })),
    onSuccess: (_r, approve) => { toast(t(approve ? "partner.approvedOk" : "partner.sentBackOk"), "ok"); setSending(false); setNote(""); void refresh(); },
  });
  if (review.status !== "draft" || (!review.review_needed && review.review_status === "none" && !partner)) return null;
  const status = review.review_status as keyof typeof TONE;
  return (
    <Card title={t("partner.title")} actions={<Badge tone={TONE[status] ?? "neutral"}>{t(`partner.status.${status}`)}</Badge>}>
      <div className="space-y-3 text-sm">
        <p className="text-muted">{t(review.review_needed || status !== "none" ? "partner.hintRequired" : "partner.hintOptional")}</p>
        {status === "changes_requested" && review.review_note && <Alert tone="warn"><strong>{t("partner.sentBackWith")}</strong> {review.review_note}</Alert>}
        {status === "approved" && <p className="text-ok">{t("partner.approvedNote")}</p>}
        <div className="flex flex-wrap gap-2">
          {canBill && status !== "requested" && status !== "approved" && <Button variant="secondary" loading={ask.isPending} onClick={() => ask.mutate()}>{t("partner.ask")}</Button>}
          {partner && status !== "approved" && <Button loading={decide.isPending && !sending} onClick={() => decide.mutate(true)}>{t("partner.approve")}</Button>}
          {partner && status !== "changes_requested" && <Button variant="secondary" onClick={() => setSending(true)}>{t("partner.sendBack")}</Button>}
        </div>
        {!partner && status === "requested" && <p className="text-xs text-muted">{t("partner.waiting")}</p>}
      </div>
      <Modal open={sending} onClose={() => setSending(false)} title={t("partner.sendBack")}
        footer={<><Button variant="secondary" onClick={() => setSending(false)}>{t("cancel")}</Button><Button loading={decide.isPending} disabled={!note.trim()} onClick={() => decide.mutate(false)}>{t("partner.sendBack")}</Button></>}>
        <Field label={t("partner.note")} required hint={t("partner.noteHint")}><Textarea value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} data-autofocus /></Field>
      </Modal>
    </Card>
  );
}
