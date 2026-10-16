import { api, Badge, DataTable, formatDate, Pager, unwrap, usePagedList, useTranslation } from "@/sdk";

/** What people wrote to the business on WhatsApp: replies to reminders, and commands from staff (Approve, Reject). */
export default function InboxTab({ companyId }: { companyId: string }) {
  const { t } = useTranslation("leadsintel");
  const list = usePagedList(["leadsintel-inbox", companyId], (limit, offset) => unwrap(api.GET("/api/v1/plugins/leadsintel/inbox", { params: { query: { company_id: companyId, limit, offset } } })), 25);
  return (
    <>
      <p className="mb-3 text-sm text-muted">{t("inboxHint")}</p>
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(m) => m.id}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
        empty={{ title: t("inboxEmpty"), hint: t("inboxEmptyHint") }}
        columns={[
          { header: t("when"), cell: (m) => formatDate(m.created_at, true) },
          { header: t("from"), cell: (m) => <span className="tnum">{m.sender}</span> },
          { header: t("message"), cell: (m) => m.body ?? (m.button_id ? t("buttonTap") : "—") },
          { header: t("handled"), hideBelow: "md", cell: (m) => <Badge tone={m.outcome === "unknown" || m.outcome === "received" ? "neutral" : "ok"}>{t(`outcome.${m.outcome}`, { defaultValue: m.outcome })}</Badge> },
        ]}
      />
    </>
  );
}
