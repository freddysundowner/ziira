import { useState } from "react";

import { api, ConfirmDialog, channelOptions, Drawer, ErrorState, Skeleton, unwrap, useChannels, useCompany, useMutation, useQueryClient, useTranslation } from "@/sdk";

import BriefText from "./BriefText";

const linkClass = "text-sm font-medium text-brand-strong hover:underline disabled:opacity-50 disabled:no-underline";

/** Two quiet links under the card: see today's note in a drawer, or send myself one now (once a day). */
export default function NoteLinks({ channel }: { channel: string }) {
  const { t } = useTranslation("command");
  const qc = useQueryClient();
  const { company } = useCompany();
  const cid = company?.id;
  const available = useChannels().data ?? [];
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [result, setResult] = useState<"sent" | "already" | string | null>(null);

  const preview = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/command/briefs/preview", { params: { query: { kind: "daily", company_id: cid } } })),
  });
  const send = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/command/briefs/send-now", { params: { query: { kind: "daily", channel, company_id: cid } } })),
    onSuccess: () => { setConfirm(false); setResult("sent"); void qc.invalidateQueries({ queryKey: ["command", "briefs"] }); },
    onError: (e) => { setConfirm(false); setResult(/already/i.test(e.message) ? "already" : e.message); },
  });

  const show = () => { setOpen(true); preview.mutate(); };
  const onSend = () => { setResult(null); if (channel === "in_app") send.mutate(); else setConfirm(true); };
  const way = channelOptions(available, channel, ["in_app"]).find((o) => o.value === channel)?.label ?? channel;

  return (
    <>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <button type="button" className={linkClass} disabled={!cid} onClick={show}>{t("note.see")}</button>
        <button type="button" className={linkClass} disabled={!cid || send.isPending} onClick={onSend}>{t("note.sendOne")}</button>
        <span role="status" aria-live="polite" className={result && result !== "sent" && result !== "already" ? "text-sm text-bad" : "text-sm text-muted"}>
          {result === "sent" ? t("note.sent") : result === "already" ? t("note.alreadySent") : result ?? ""}
        </span>
      </div>
      <Drawer open={open} onClose={() => setOpen(false)} title={t("note.seeTitle")}>
        {preview.error ? <ErrorState message={preview.error.message} onRetry={() => preview.mutate()} />
          : !preview.data ? <Skeleton className="h-40 w-full" />
            : <BriefText body={preview.data.body} />}
      </Drawer>
      <ConfirmDialog open={confirm} onClose={() => setConfirm(false)} onConfirm={() => send.mutate()} busy={send.isPending}
        title={t("sendNowTitle")} message={t("sendNowMessage", { channel: way })} confirmLabel={t("note.sendOne")} />
    </>
  );
}
