import { Plus } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, DataTable, Input, PageHeader, Pager, Select, unwrap, useCan, useDebounced, usePagedList, useTranslation,
} from "@/sdk";

import { CustomerForm } from "../components/CustomerForm";
import { customerTone } from "../logic";
import { customerPath } from "../public";

export default function CustomersPage() {
  const { t } = useTranslation("crm");
  const canManage = useCan("customers.manage");
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [group, setGroup] = useState("");
  const q = useDebounced(search.trim());
  const g = useDebounced(group.trim());
  const filtered = !!(q || status || g);
  const list = usePagedList(["customers", q, status, g], (limit, offset) =>
    unwrap(api.GET("/api/v1/crm/customers", { params: { query: { search: q || undefined, status: status || undefined, group: g || undefined, limit, offset } } })));

  return (
    <>
      <PageHeader title={t("title")} description={t("hint")}
        actions={canManage && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newCustomer")}</Button>} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
        rowKey={(c) => c.id} rowHref={(c) => customerPath(c.id)}
        toolbar={
          <>
            <Input className="max-w-xs" aria-label={t("search")} placeholder={t("search")} value={search} onChange={(e) => setSearch(e.target.value)} />
            <Select className="w-40" aria-label={t("status")} value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>
              {(["active", "on_hold", "inactive"] as const).map((s) => <option key={s} value={s}>{t(`statuses.${s}`)}</option>)}
            </Select>
            <Input className="w-40" aria-label={t("group")} placeholder={t("group")} value={group} onChange={(e) => setGroup(e.target.value)} />
          </>
        }
        empty={{
          title: filtered ? t("noMatch") : t("empty"), hint: filtered ? undefined : t("emptyHint"),
          action: canManage && !filtered ? <Button onClick={() => setCreating(true)}>{t("newCustomer")}</Button> : undefined,
        }}
        columns={[
          { header: t("code"), sortValue: (c) => c.code, cell: (c) => <span className="font-mono text-xs font-medium">{c.code}</span> },
          { header: t("name"), sortValue: (c) => c.name, cell: (c) => <span className="font-medium">{c.name}</span> },
          { header: t("phone"), hideBelow: "sm", cell: (c) => c.phone ?? "—" },
          { header: t("group"), hideBelow: "md", cell: (c) => c.customer_group ?? "—" },
          { header: t("terms"), hideBelow: "lg", align: "right", cell: (c) => t("days", { count: c.payment_terms_days }) },
          { header: t("status"), cell: (c) => <Badge tone={customerTone(c.status)}>{t(`statuses.${c.status}`, c.status)}</Badge> },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <CustomerForm open={creating} onClose={() => setCreating(false)} />
    </>
  );
}
