import { useState } from "react";

import { api, Badge, DataTable, formatDate, humanise, Pager, Select, unwrap, usePagedList, useTranslation, type BadgeTone } from "@/sdk";

const TONE: Record<string, BadgeTone> = { sent: "ok", queued: "info", failed: "bad", skipped: "neutral" };

export default function LogTab({ companyId }: { companyId: string | undefined }) {
  const { t } = useTranslation("kernel");
  const [channel, setChannel] = useState("");
  const [status, setStatus] = useState("");
  const list = usePagedList(["notifications", companyId, channel, status], (limit, offset) =>
    unwrap(api.GET("/api/v1/notifications", { params: { query: {
      company_id: companyId!, channel: (channel || undefined) as "sms" | undefined, status: status || undefined, limit, offset,
    } } })), 25, !!companyId);
  if (!companyId) return null;
  return (
    <DataTable
      rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(n) => n.id}
      toolbar={
        <>
          <Select aria-label={t("channel")} className="w-auto" value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="">{t("allChannels")}</option><option value="sms">{t("sms")}</option><option value="email">{t("emailChannel")}</option>
          </Select>
          <Select aria-label={t("status")} className="w-auto" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("allStatuses")}</option>
            {["queued", "sent", "failed", "skipped"].map((s) => <option key={s} value={s}>{t(`nStatus.${s}`)}</option>)}
          </Select>
        </>
      }
      footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      empty={{ title: t("noMessages"), hint: t("noMessagesHint") }}
      columns={[
        { header: t("when"), cell: (n) => formatDate(n.created_at, true) },
        { header: t("channel"), hideBelow: "sm", cell: (n) => (n.channel === "sms" ? t("sms") : t("emailChannel")) },
        { header: t("recipient"), cell: (n) => <span className="tnum">{n.recipient}</span> },
        { header: t("subject"), hideBelow: "md", cell: (n) => n.subject ?? (n.ref_type ? humanise(n.ref_type) : "—") },
        { header: t("status"), cell: (n) => <><Badge tone={TONE[n.status] ?? "neutral"}>{t(`nStatus.${n.status}`, { defaultValue: humanise(n.status) })}</Badge>{n.error && <span className="mt-1 block max-w-xs truncate text-xs text-bad" title={n.error}>{n.error}</span>}</> },
        { header: t("attempts"), hideBelow: "lg", align: "right", cell: (n) => n.attempts },
      ]}
    />
  );
}
