import { Plus } from "lucide-react";
import { useState } from "react";

import { api, Button, DataTable, Input, PageHeader, Pager, Select, unwrap, useCan, useDebounced, usePagedList, useTranslation } from "@/sdk";

import { Status } from "../components/Status";
import { SupplierDrawer } from "../components/SupplierDrawer";
import { SUPPLIER_STATUSES } from "../lib";

export default function SuppliersPage() {
  const { t } = useTranslation("purchasing");
  const canManage = useCan("suppliers.manage");
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const q = useDebounced(search.trim());
  const list = usePagedList(["purchasing", "suppliers", q, status], (limit, offset) =>
    unwrap(api.GET("/api/v1/purchasing/suppliers", { params: { query: { search: q || undefined, status: status || undefined, limit, offset } } })));
  const filtered = !!q || !!status;

  return (
    <>
      <PageHeader title={t("suppliers")} description={t("suppliersHint")} actions={canManage && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newSupplier")}</Button>} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(s) => s.id}
        rowHref={(s) => `/suppliers/${s.id}`}
        toolbar={<>
          <Input className="max-w-sm" aria-label={t("searchSuppliers")} placeholder={t("searchSuppliers")} value={search} onChange={(e) => setSearch(e.target.value)} />
          <Select className="w-44" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">{t("allStatuses")}</option>
            {SUPPLIER_STATUSES.map((s) => <option key={s} value={s}>{t(`statuses.${s}`)}</option>)}
          </Select>
        </>}
        empty={{ title: filtered ? t("noSupplierMatch") : t("noSuppliers"), hint: filtered ? undefined : t("noSuppliersHint"), action: canManage && !filtered ? <Button onClick={() => setCreating(true)}>{t("newSupplier")}</Button> : undefined }}
        columns={[
          { header: t("code"), sortValue: (s) => s.code, cell: (s) => <span className="font-mono text-xs font-medium">{s.code}</span> },
          { header: t("name"), sortValue: (s) => s.name, cell: (s) => <span className="font-medium">{s.name}</span> },
          { header: t("phone"), hideBelow: "sm", cell: (s) => s.phone ?? "—" },
          { header: t("email"), hideBelow: "lg", cell: (s) => s.email ?? "—" },
          { header: t("terms"), hideBelow: "md", align: "right", cell: (s) => t("days", { count: s.payment_terms_days }) },
          { header: t("status"), cell: (s) => <Status status={s.status} /> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      {creating && <SupplierDrawer onClose={() => setCreating(false)} />}
    </>
  );
}
