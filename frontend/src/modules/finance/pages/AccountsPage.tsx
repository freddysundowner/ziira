import { Lock, Plus } from "lucide-react";
import { useMemo, useState } from "react";

import {
  api, Badge, Button, Checkbox, DataTable, humanise, PageHeader, StatusBadge, toast, unwrap, useCan, useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import { type Account, useAccounts } from "../api";
import { AccountDrawer } from "../components/AccountDrawer";
import { orderAccounts } from "../lib";
import { ScopeSelects, useScope } from "../scope";

/** The chart of accounts as a tree. Control accounts are kept by their sub-ledgers: they show a lock and cannot be posted to by hand or switched off. */
export default function AccountsPage() {
  const { t } = useTranslation("finance");
  const qc = useQueryClient();
  const scope = useScope();
  const canManage = useCan("accounts.manage");
  const [inactive, setInactive] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Account | null>(null);
  const accounts = useAccounts(scope.companyId, inactive);
  const rows = useMemo(() => orderAccounts(accounts.data ?? []), [accounts.data]);

  const setup = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/finance/companies/{company_id}/books", { params: { path: { company_id: scope.companyId } } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["finance"] }); toast(t("booksReady"), "ok"); },
  });

  return (
    <>
      <PageHeader title={t("accounts.title")} description={t("accounts.hint")}
        actions={<>
          <ScopeSelects scope={scope} branch={false} />
          {canManage && <Button onClick={() => setCreating(true)} disabled={!scope.companyId}><Plus className="h-4 w-4" />{t("accounts.new")}</Button>}
        </>} />
      <DataTable
        rows={accounts.data ? rows : undefined} loading={accounts.isLoading || scope.loading} error={accounts.error?.message} onRetry={() => void accounts.refetch()}
        rowKey={(r) => r.account.id} dense pageSize={100}
        searchText={(r) => `${r.account.code} ${r.account.name} ${r.account.type}`} searchPlaceholder={t("accounts.search")}
        toolbar={<Checkbox label={t("accounts.showInactive")} checked={inactive} onChange={(e) => setInactive(e.target.checked)} />}
        empty={{ title: t("accounts.empty"), hint: t("accounts.emptyHint"), action: canManage ? <Button loading={setup.isPending} onClick={() => setup.mutate()}>{t("accounts.setupBooks")}</Button> : undefined }}
        columns={[
          { header: t("code"), sortValue: (r) => r.account.code, cell: (r) => <span className="font-mono text-xs font-medium">{r.account.code}</span> },
          {
            header: t("name"), cell: (r) => (
              <span className="flex items-center gap-1.5" style={{ paddingLeft: r.depth * 18 }}>
                <span className={r.depth === 0 ? "font-semibold" : "font-medium"}>{r.account.name}</span>
                {r.account.is_control && <Lock aria-label={t("accounts.control")} className="h-3.5 w-3.5 text-muted" />}
              </span>),
          },
          { header: t("type"), hideBelow: "sm", cell: (r) => <Badge>{t(`accountTypes.${r.account.type}`, humanise(r.account.type))}</Badge> },
          { header: t("accounts.subtype"), hideBelow: "lg", cell: (r) => (r.account.subtype ? humanise(r.account.subtype) : "—") },
          { header: t("accounts.postable"), hideBelow: "md", cell: (r) => (r.account.is_control ? <Badge tone="info">{t("accounts.control")}</Badge> : <span className="text-muted">{t("accounts.byHand")}</span>) },
          { header: t("status"), hideBelow: "md", cell: (r) => <StatusBadge status={r.account.is_active ? "active" : "inactive"} /> },
          { header: "", align: "right", cell: (r) => canManage && <Button variant="ghost" size="sm" onClick={() => setEditing(r.account)}>{t("edit")}</Button> },
        ]}
      />
      {!accounts.isLoading && !accounts.error && accounts.data && accounts.data.length > 0 && <p className="mt-3 text-xs text-muted">{t("accounts.controlHint")}</p>}
      <AccountDrawer open={creating} onClose={() => setCreating(false)} companyId={scope.companyId} />
      <AccountDrawer open={!!editing} account={editing ?? undefined} onClose={() => setEditing(null)} companyId={scope.companyId} />
    </>
  );
}
