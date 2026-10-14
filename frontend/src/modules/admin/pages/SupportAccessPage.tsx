import { Plus } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, ConfirmDialog, DataTable, formatDate, PageHeader, StatusBadge, Tabs, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import AccessLogTab from "./support/AccessLogTab";
import NewGrantDrawer from "./support/NewGrantDrawer";

type Grant = Schemas["SupportGrantOut"];
type Tab = "grants" | "log";

/** Lets the business give Ziira support time-limited access, shows who used it, and ends it at any moment. */
export default function SupportAccessPage() {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("grants");
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<Grant | null>(null);
  const grants = useQuery({ queryKey: ["support-grants"], queryFn: () => unwrap(api.GET("/api/v1/support/grants", { params: { query: { limit: 200 } } })) });
  const revoke = useMutation({
    mutationFn: (g: Grant) => unwrap(api.POST("/api/v1/support/grants/{grant_id}/revoke", { params: { path: { grant_id: g.id } } })),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["support-grants"] });
      void qc.invalidateQueries({ queryKey: ["support-banner"] });
      toast(t("support.revoked"), "ok");
      setRevoking(null);
    },
  });

  return (
    <>
      <PageHeader title={t("support.title")} description={t("support.hint")} actions={<Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("support.newGrant")}</Button>} />
      <div className="mb-4 space-y-1 rounded-xl border border-line bg-surface p-4 text-sm text-muted">
        <p>{t("support.intro1")}</p>
        <p>{t("support.intro2")}</p>
        <p>{t("support.intro3")}</p>
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "grants", label: t("support.tabGrants") }, { id: "log", label: t("support.tabLog") }]} />
      {tab === "log" ? <AccessLogTab /> : (
        <DataTable
          rows={grants.data} loading={grants.isLoading} error={grants.error?.message} onRetry={() => void grants.refetch()} rowKey={(g) => g.id} pageSize={20}
          empty={{ title: t("support.none"), hint: t("support.noneHint"), action: <Button onClick={() => setCreating(true)}>{t("support.newGrant")}</Button> }}
          columns={[
            { header: t("support.reasonCol"), cell: (g) => <GrantCell grant={g} /> },
            { header: t("support.levelCol"), hideBelow: "sm", cell: (g) => <Badge tone={g.level === "full" ? "warn" : "neutral"}>{t(`support.levelName.${g.level}`, { defaultValue: g.level })}</Badge> },
            { header: t("support.givenBy"), hideBelow: "lg", cell: (g) => g.created_by_name ?? "—" },
            { header: t("support.until"), hideBelow: "md", sortValue: (g) => g.expires_at, cell: (g) => formatDate(g.revoked_at ?? g.expires_at, true) },
            { header: t("status"), cell: (g) => <StatusBadge status={g.status} /> },
            { header: "", align: "right", cell: (g) => g.status === "active" && <Button size="sm" variant="ghost" onClick={() => setRevoking(g)}>{t("support.revoke")}</Button> },
          ]}
        />
      )}
      <NewGrantDrawer open={creating} onClose={() => setCreating(false)} />
      <ConfirmDialog open={!!revoking} onClose={() => setRevoking(null)} danger busy={revoke.isPending} title={t("support.revoke")} confirmLabel={t("support.revoke")}
        message={t("support.revokeAsk")} onConfirm={() => revoking && revoke.mutate(revoking)} />
    </>
  );
}

/** The reason, with who opened the business under this access and how much they did. */
function GrantCell({ grant }: { grant: Grant }) {
  const { t } = useTranslation("kernel");
  return (
    <div className="min-w-0">
      <p className="font-medium">{grant.reason}</p>
      {grant.note && <p className="text-xs text-muted">{grant.note}</p>}
      <ul className="mt-1 space-y-0.5 text-xs text-muted">
        {grant.sessions.length === 0 ? <li>{t("support.noSessions")}</li> : grant.sessions.map((s) => (
          <li key={s.id}>{t("support.sessionLine", { name: s.operator_name, count: s.requests, when: formatDate(s.started_at, true) })}</li>
        ))}
      </ul>
    </div>
  );
}
