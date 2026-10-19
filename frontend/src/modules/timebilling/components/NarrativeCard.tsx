import { useEffect, useState } from "react";

import { api, Button, Card, Field, Textarea, toast, unwrap, useMutation, useTranslation } from "@/sdk";

import { useRefresh } from "../hooks";
import type { Review } from "../types";
import { DownloadButton } from "./DownloadButton";

/** The account of the work behind the invoice: written from the entries' notes, edited by a person, sent with the invoice. */
export function NarrativeCard({ review, editable }: { review: Review; editable: boolean }) {
  const { t } = useTranslation("timebilling");
  const refresh = useRefresh();
  const [text, setText] = useState("");
  useEffect(() => { setText(review.narrative ?? ""); }, [review.id, review.narrative]);
  const path = { batch_id: review.id };
  const write = useMutation({
    mutationFn: (intoLines: boolean) => unwrap(api.POST("/api/v1/timebilling/invoice-reviews/{batch_id}/narrative", { params: { path }, body: { into_lines: intoLines } })),
    onSuccess: (_r, intoLines) => { toast(t(intoLines ? "narrative.linesDone" : "narrative.written"), "ok"); void refresh(); },
  });
  const save = useMutation({
    mutationFn: () => unwrap(api.PATCH("/api/v1/timebilling/invoice-reviews/{batch_id}", { params: { path }, body: { narrative: text.trim() || null } })),
    onSuccess: () => void refresh(),
  });
  const hasTime = review.lines.some((l) => l.kind === "time");
  if (!editable && !review.narrative) return null;
  return (
    <Card title={t("narrative.title")} description={t("narrative.hint")}
      actions={<DownloadButton fileName="time-schedule.csv" request={() => api.GET("/api/v1/timebilling/invoice-reviews/{batch_id}/schedule.csv", { params: { path }, parseAs: "blob" })}>{t("narrative.schedule")}</DownloadButton>}>
      <div className="space-y-3">
        {editable ? (
          <Field label={t("narrative.text")} hint={t("narrative.textHint")}>
            <Textarea rows={6} value={text} maxLength={4000} onChange={(e) => setText(e.target.value)} onBlur={() => { if (text.trim() !== (review.narrative ?? "")) save.mutate(); }} />
          </Field>
        ) : <p className="whitespace-pre-wrap text-sm">{review.narrative}</p>}
        {editable && hasTime && (
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" loading={write.isPending && !write.variables} onClick={() => write.mutate(false)}>{t("narrative.write")}</Button>
            <Button variant="secondary" loading={write.isPending && !!write.variables} onClick={() => write.mutate(true)}>{t("narrative.intoLines")}</Button>
          </div>
        )}
      </div>
    </Card>
  );
}
