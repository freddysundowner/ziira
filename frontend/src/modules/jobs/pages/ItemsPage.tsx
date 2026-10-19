import { Plus } from "lucide-react";
import { useState } from "react";

import { api, Badge, Button, DataTable, Input, PageHeader, Pager, unwrap, useCan, useDebounced, usePagedList, useTranslation } from "@/sdk";

import { ItemDrawer } from "../components/ItemDrawer";
import { identifierText } from "../lib";
import { assetHref } from "../public";

/** The things customers bring in: vehicles, phones, garments, places. */
export default function ItemsPage() {
  const { t } = useTranslation("jobs");
  const canManage = useCan("jobs.manage");
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim());
  const list = usePagedList(["jobs", "items", q], (limit, offset) =>
    unwrap(api.GET("/api/v1/jobs/assets", { params: { query: { search: q || undefined, limit, offset } } })));
  return (
    <>
      <PageHeader title={t("menu.items")} description={t("items.hint")} actions={canManage && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("items.new")}</Button>} />
      <DataTable rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()}
        rowKey={(a) => a.id} rowHref={(a) => assetHref(a.id)}
        toolbar={<Input className="max-w-sm" aria-label={t("items.search")} placeholder={t("items.search")} value={search} onChange={(e) => setSearch(e.target.value)} />}
        empty={{ title: q ? t("items.noMatch") : t("items.empty"), hint: q ? undefined : t("items.emptyHint"), action: canManage && !q ? <Button onClick={() => setCreating(true)}>{t("items.new")}</Button> : undefined }}
        columns={[
          { header: t("items.item"), sortValue: (a) => a.label, cell: (a) => <span className="font-medium">{a.label}</span> },
          { header: t("receive.itemKind"), hideBelow: "sm", cell: (a) => <Badge tone="neutral">{a.kind}</Badge> },
          { header: t("receive.identifiers"), hideBelow: "md", cell: (a) => identifierText(a.identifiers) || "—" },
          { header: t("items.status"), hideBelow: "lg", cell: (a) => (a.is_active ? t("items.inUse") : t("items.retired")) },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />} />
      {creating && <ItemDrawer onClose={() => setCreating(false)} />}
    </>
  );
}
