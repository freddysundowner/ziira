import { Link } from "react-router-dom";

import { api, Badge, Button, DataTable, money, PageHeader, unwrap, useCan, useQuery, useTranslation } from "@/sdk";
import { customerPath } from "@/modules/crm/public";
import { useState } from "react";

import { ClientTermsDrawer } from "../components/ClientTermsDrawer";
import { CompanyPicker } from "../components/CompanyBar";
import { useStartReview } from "../components/useStartReview";
import { useWorkCompany } from "../hooks";
import type { Client } from "../types";

/** The clients the business bills for time: their projects, what is waiting to be invoiced, how they pay. */
export default function ClientsPage() {
  const { t } = useTranslation("timebilling");
  const canBill = useCan("time.bill");
  const canManage = useCan("projects.manage");
  const { companyId, companies, setCompanyId, currency } = useWorkCompany();
  const [editing, setEditing] = useState<Client | null>(null);
  const start = useStartReview(companyId);
  const list = useQuery({
    queryKey: ["timebilling", "clients", companyId], enabled: !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/timebilling/clients", { params: { query: { company_id: companyId } } })),
  });

  return (
    <>
      <PageHeader title={t("clients.title")} description={t("clients.hint")} actions={<CompanyPicker companies={companies} value={companyId} onChange={setCompanyId} />} />
      <DataTable
        rows={list.data} loading={list.isLoading} error={list.error?.message} onRetry={() => void list.refetch()} rowKey={(c) => c.customer_id}
        searchText={(c) => c.name} searchPlaceholder={t("clients.search")}
        empty={{ title: t("clients.empty"), hint: t("clients.emptyHint"), action: <Link className="text-sm font-medium text-brand-strong hover:underline" to="/projects">{t("projects.title")}</Link> }}
        columns={[
          { header: t("client"), sortValue: (c) => c.name, cell: (c) => <Link className="font-medium hover:underline" to={customerPath(c.customer_id)}>{c.name}</Link> },
          { header: t("clients.projects"), align: "right", hideBelow: "sm", sortValue: (c) => c.projects, cell: (c) => <span className="tnum">{c.projects}</span> },
          { header: t("clients.unbilled"), align: "right", sortValue: (c) => Number(c.unbilled_amount), cell: (c) => <span className="tnum font-medium">{money(c.unbilled_amount, currency)}</span> },
          { header: t("clients.terms"), hideBelow: "md", cell: (c) => (c.payment_terms_days === null ? <span className="text-muted">{t("clients.businessDefault")}</span> : t("clients.days", { count: c.payment_terms_days })) },
          { header: t("clients.grouping"), hideBelow: "lg", cell: (c) => (c.invoice_group_by ? <Badge>{t(`grouping.${c.invoice_group_by}`)}</Badge> : <span className="text-muted">—</span>) },
          {
            header: "", align: "right",
            cell: (c) => (
              <span className="flex justify-end gap-1">
                {canManage && <Button size="sm" variant="ghost" onClick={() => setEditing(c)}>{t("clients.editSettings")}</Button>}
                {canBill && <Button size="sm" variant="secondary" disabled={c.projects === 0} loading={start.isPending && start.pending?.clientId === c.customer_id} onClick={() => start.start({ clientId: c.customer_id })}>{t("clients.startReview")}</Button>}
              </span>
            ),
          },
        ]} />
      {start.dialog}
      <ClientTermsDrawer client={editing} companyId={companyId} onClose={() => setEditing(null)} />
    </>
  );
}
