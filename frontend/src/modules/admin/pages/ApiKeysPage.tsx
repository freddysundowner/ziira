import { MoreHorizontal, Plus } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, ConfirmDialog, DataTable, formatDate, Menu, PageHeader, StatusBadge, toast, unwrap, useCompanies, useMutation, useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import NewKeyDrawer from "./apikeys/NewKeyDrawer";
import RotateDialog from "./apikeys/RotateDialog";
import SecretDialog from "./apikeys/SecretDialog";

type Key = Schemas["ApiKeyOut"];

/** Keys for server-to-server integrations. The secret is shown once, when the key is made. */
export default function ApiKeysPage() {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<{ name: string; key: string } | null>(null);
  const [revoking, setRevoking] = useState<Key | null>(null);
  const [rotating, setRotating] = useState<Key | null>(null);
  const companies = useCompanies();
  const keys = useQuery({ queryKey: ["api-keys"], queryFn: () => unwrap(api.GET("/api/v1/api-keys")) });
  const revoke = useMutation({
    mutationFn: (k: Key) => unwrap(api.DELETE("/api/v1/api-keys/{key_id}", { params: { path: { key_id: k.id } } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["api-keys"] }); toast(t("keyRevoked"), "ok"); setRevoking(null); },
  });
  const state = (k: Key) => (k.revoked_at ? "revoked" : k.expires_at && new Date(k.expires_at) < new Date() ? "expired" : "active");

  return (
    <>
      <PageHeader title={t("apiKeys")} description={t("apiKeysHint")} actions={<Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newKey")}</Button>} />
      <DataTable
        rows={keys.data} loading={keys.isLoading} error={keys.error?.message} onRetry={() => void keys.refetch()} rowKey={(k) => k.id}
        searchText={(k) => k.name} searchPlaceholder={t("searchKeys")} pageSize={20}
        empty={{ title: t("noKeys"), hint: t("noKeysHint"), action: <Button onClick={() => setCreating(true)}>{t("newKey")}</Button> }}
        columns={[
          { header: t("keyName"), sortValue: (k) => k.name, cell: (k) => <span className="font-medium">{k.name}</span> },
          { header: t("scopes"), hideBelow: "md", cell: (k) => <Badge>{t("scopeCount", { count: k.scopes.length })}</Badge> },
          { header: t("keys.limits"), hideBelow: "lg", cell: (k) => (
            <div className="flex flex-wrap gap-1">
              <Badge tone={k.read_only ? "ok" : "neutral"}>{k.read_only ? t("keys.readOnlyBadge") : t("keys.readWrite")}</Badge>
              {k.company_id && <Badge>{companies.data?.find((c) => c.id === k.company_id)?.name ?? t("keys.oneCompany")}</Badge>}
              <Badge>{k.rate_limit_per_minute ? t("keys.perMinute", { count: k.rate_limit_per_minute }) : t("keys.defaultRate")}</Badge>
            </div>) },
          { header: t("keys.lastUsed"), hideBelow: "md", sortValue: (k) => k.last_used_at ?? "", cell: (k) => (
            k.last_used_at ? <div><p>{formatDate(k.last_used_at, true)}</p><p className="text-xs text-muted">{t("keys.uses", { count: k.use_count })}{k.last_ip ? ` · ${k.last_ip}` : ""}</p></div> : <span className="text-muted">{t("keys.neverUsed")}</span>) },
          { header: t("createdOn"), hideBelow: "lg", sortValue: (k) => k.created_at, cell: (k) => formatDate(k.created_at) },
          { header: t("expires"), hideBelow: "lg", cell: (k) => (k.expires_at ? formatDate(k.expires_at) : t("never")) },
          { header: t("status"), cell: (k) => <StatusBadge status={state(k)} /> },
          { header: "", align: "right", cell: (k) => !k.revoked_at && (
            <Menu label={t("keys.actions", { name: k.name })} trigger={<MoreHorizontal className="h-4 w-4" />}
              items={[{ label: t("keys.rotate"), onSelect: () => setRotating(k) }, "separator", { label: t("revoke"), danger: true, onSelect: () => setRevoking(k) }]} />) },
        ]}
      />
      <NewKeyDrawer open={creating} onClose={() => setCreating(false)} onCreated={(name, key) => { setCreating(false); setSecret({ name, key }); }} />
      <SecretDialog secret={secret} onClose={() => setSecret(null)} />
      <RotateDialog target={rotating} onClose={() => setRotating(null)} onRotated={(name, key) => { setRotating(null); setSecret({ name, key }); }} />
      <ConfirmDialog open={!!revoking} onClose={() => setRevoking(null)} danger busy={revoke.isPending} title={t("revoke")} confirmLabel={t("revoke")}
        message={t("revokeAsk", { name: revoking?.name })} onConfirm={() => revoking && revoke.mutate(revoking)} />
    </>
  );
}
