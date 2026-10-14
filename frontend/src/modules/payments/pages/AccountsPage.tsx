import { KeyRound, Pencil, Plus } from "lucide-react";
import { useState } from "react";

import { Badge, Button, Checkbox, DataTable, IconButton, PageHeader, StatusBadge, useCan, useCompany, useTranslation } from "@/sdk";

import { AccountForm } from "../components/AccountForm";
import { AccountSecurity } from "../components/AccountSecurity";
import { usePaymentAccounts } from "../components/usePaymentAccounts";
import type { PaymentAccount } from "../types";

/** Cash drawers, mobile money collections, bank and card accounts the business takes or pays money through. */
export default function AccountsPage() {
  const { t } = useTranslation("payments");
  const canManage = useCan("payments.manage");
  const { companies } = useCompany();
  const [inactive, setInactive] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<PaymentAccount | undefined>();
  const [securing, setSecuring] = useState<PaymentAccount | null>(null);
  const q = usePaymentAccounts({ includeInactive: inactive });
  const providers = [...new Set((q.data ?? []).map((a) => a.provider))];
  const branchName = (a: PaymentAccount) => companies.find((c) => c.id === a.company_id)?.branches.find((b) => b.id === a.branch_id)?.name;

  return (
    <>
      <PageHeader title={t("accountsTitle")} description={t("accountsHint")} actions={canManage && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newAccount")}</Button>} />
      <DataTable
        rows={q.data} loading={q.isLoading} error={q.error?.message} onRetry={() => void q.refetch()} rowKey={(a) => a.id}
        searchText={(a) => `${a.name} ${a.shortcode ?? ""}`} searchPlaceholder={t("searchAccounts")}
        toolbar={<Checkbox label={t("showInactive")} checked={inactive} onChange={(e) => setInactive(e.target.checked)} />}
        empty={{ title: t("noAccounts"), hint: t("noAccountsHint"), action: canManage ? <Button onClick={() => setCreating(true)}>{t("newAccount")}</Button> : undefined }}
        columns={[
          { header: t("name"), sortValue: (a) => a.name, cell: (a) => <span className="font-medium">{a.name}</span> },
          { header: t("kind"), cell: (a) => <Badge>{t(`methods.${a.kind}`, a.kind)}</Badge> },
          { header: t("numberOrCode"), hideBelow: "sm", cell: (a) => a.shortcode ?? a.bank_account_masked ?? "—" },
          { header: t("provider"), hideBelow: "md", cell: (a) => a.provider },
          { header: t("branch"), hideBelow: "lg", cell: (a) => branchName(a) ?? t("allBranches") },
          { header: t("status"), cell: (a) => <StatusBadge status={a.is_active ? "active" : "inactive"} /> },
          {
            header: "", align: "right",
            cell: (a) => canManage && (
              <span className="inline-flex">
                {a.kind === "mobile_money" && <IconButton label={t("connection", { name: a.name })} onClick={() => setSecuring(a)}><KeyRound className="h-4 w-4" /></IconButton>}
                <IconButton label={t("editAccount")} onClick={() => setEditing(a)}><Pencil className="h-4 w-4" /></IconButton>
              </span>
            ),
          },
        ]}
      />
      <AccountForm open={creating} onClose={() => setCreating(false)} providers={providers} />
      <AccountForm open={!!editing} onClose={() => setEditing(undefined)} account={editing} providers={providers} />
      <AccountSecurity account={securing} onClose={() => setSecuring(null)} />
    </>
  );
}
