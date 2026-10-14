import { useState } from "react";

import { api, Badge, DataTable, Drawer, ErrorState, formatDate, Pager, Skeleton, unwrap, usePagedList, useQuery, useQueryClient, useTranslation } from "@/sdk";

import BriefText from "./BriefText";

/** Briefs sent to me, newest first; opening one marks it read. */
export default function BriefHistory() {
  const { t } = useTranslation("command");
  const qc = useQueryClient();
  const [openId, setOpenId] = useState<string | null>(null);
  const list = usePagedList(["command", "briefs"], (limit, offset) => unwrap(api.GET("/api/v1/command/briefs", { params: { query: { limit, offset } } })), 10);
  const detail = useQuery({
    enabled: !!openId, queryKey: ["command", "brief", openId],
    queryFn: async () => {
      const brief = await unwrap(api.GET("/api/v1/command/briefs/{brief_id}", { params: { path: { brief_id: openId! } } }));
      void qc.invalidateQueries({ queryKey: ["command", "briefs"] });
      return brief;
    },
  });

  return (
    <>
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(b) => b.id}
        empty={{ title: t("noBriefs"), hint: t("noBriefsHint") }}
        columns={[
          { header: t("date"), cell: (b) => <button className="text-left font-medium hover:underline" onClick={() => setOpenId(b.id)}>{formatDate(b.brief_date)}</button> },
          { header: t("which"), hideBelow: "sm", cell: (b) => t(`kind.${b.kind}`) },
          { header: t("subject"), hideBelow: "md", cell: (b) => <span className="text-muted">{b.subject}</span> },
          { header: t("sentVia"), hideBelow: "sm", cell: (b) => t(`channels.${b.delivered_via}`, b.delivered_via) },
          { header: t("status"), cell: (b) => <Badge tone={b.read_at ? "neutral" : "brand"}>{b.read_at ? t("read") : t("unread")}</Badge> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <Drawer open={!!openId} onClose={() => setOpenId(null)} title={t("briefTitle")}>
        {detail.error ? <ErrorState message={detail.error.message} onRetry={() => void detail.refetch()} />
          : !detail.data ? <Skeleton className="h-40 w-full" />
            : <BriefText body={detail.data.body} />}
      </Drawer>
    </>
  );
}
