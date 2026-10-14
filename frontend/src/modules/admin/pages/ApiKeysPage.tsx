import { Plus } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, ConfirmDialog, DataTable, formatDate, PageHeader, StatusBadge, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import NewKeyDrawer from "./apikeys/NewKeyDrawer";
import SecretDialog from "./apikeys/SecretDialog";

type Key = Schemas["ApiKeyOut"];

/** Keys for server-to-server integrations. The secret is shown once, when the key is made. */
export default function ApiKeysPage() {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<{ name: string; key: string } | null>(null);
  const [revoking, setRevoking] = useState<Key | null>(null);
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
          { header: t("createdOn"), hideBelow: "sm", sortValue: (k) => k.created_at, cell: (k) => formatDate(k.created_at) },
          { header: t("expires"), hideBelow: "lg", cell: (k) => (k.expires_at ? formatDate(k.expires_at) : t("never")) },
          { header: t("status"), cell: (k) => <StatusBadge status={state(k)} /> },
          { header: "", align: "right", cell: (k) => !k.revoked_at && <Button size="sm" variant="ghost" onClick={() => setRevoking(k)}>{t("revoke")}</Button> },
        ]}
      />
      <NewKeyDrawer open={creating} onClose={() => setCreating(false)} onCreated={(name, key) => { setCreating(false); setSecret({ name, key }); }} />
      <SecretDialog secret={secret} onClose={() => setSecret(null)} />
      <ConfirmDialog open={!!revoking} onClose={() => setRevoking(null)} danger busy={revoke.isPending} title={t("revoke")} confirmLabel={t("revoke")}
        message={t("revokeAsk", { name: revoking?.name })} onConfirm={() => revoking && revoke.mutate(revoking)} />
    </>
  );
}
