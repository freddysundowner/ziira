import { Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { customerPath } from "@/modules/crm/public";
import { api, Attachments, Badge, Button, Card, CustomFields, DataTable, DetailList, ErrorState, formatDate, PageHeader, Skeleton, unwrap, useCan, useQuery, useTranslation } from "@/sdk";

import { ItemDrawer } from "../components/ItemDrawer";
import { StageBadge } from "../components/StageBadge";
import { useCustomer, useUnit } from "../hooks";
import { identifierText } from "../lib";
import { jobHref } from "../public";

/** One item customers brought in, with every job it has had. */
export default function ItemPage() {
  const { t } = useTranslation("jobs");
  const { assetId = "" } = useParams();
  const canManage = useCan("jobs.manage");
  const hasCustomers = useUnit("crm");
  const [editing, setEditing] = useState(false);
  const asset = useQuery({ queryKey: ["jobs", "item", assetId], queryFn: () => unwrap(api.GET("/api/v1/jobs/assets/{asset_id}", { params: { path: { asset_id: assetId } } })) });
  const owner = useCustomer(hasCustomers ? asset.data?.customer_id : null);
  if (asset.error) return <ErrorState title={t("items.loadFailed")} message={asset.error.message} onRetry={() => void asset.refetch()} />;
  if (!asset.data) return <Skeleton className="h-64" />;
  const a = asset.data;
  return (
    <>
      <PageHeader back={{ to: "/jobs/items", label: t("menu.items") }} title={a.label}
        description={<span className="flex items-center gap-2"><Badge tone="neutral">{a.kind}</Badge>{!a.is_active && <Badge tone="warn">{t("items.retired")}</Badge>}</span>}
        actions={<>
          {canManage && <Button variant="secondary" onClick={() => setEditing(true)}><Pencil className="h-4 w-4" />{t("actions.edit")}</Button>}
          {canManage && <Link to={`/jobs/new?asset=${a.id}`}><Button><Plus className="h-4 w-4" />{t("items.newJob")}</Button></Link>}
        </>} />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <DataTable rows={a.jobs} rowKey={(j) => j.id} rowHref={(j) => jobHref(j.id)} empty={{ title: t("items.noJobs"), hint: t("items.noJobsHint") }}
          columns={[
            { header: t("list.number"), cell: (j) => <span className="tnum font-medium">{j.number}</span> },
            { header: t("list.job"), cell: (j) => j.title },
            { header: t("list.stage"), cell: (j) => <StageBadge stage={j.status} /> },
            { header: t("list.received"), hideBelow: "sm", cell: (j) => formatDate(j.received_at) },
          ]} />
        <aside className="space-y-4">
          <Card title={t("items.details")}>
            <DetailList items={[
              { label: t("receive.identifiers"), value: identifierText(a.identifiers) || "—" },
              { label: t("receive.customer"), value: a.customer_id && owner.data ? <Link className="text-brand-strong hover:underline" to={customerPath(a.customer_id)}>{owner.data.name}</Link> : "—" },
              { label: t("garage.workshop.odometerIn"), value: a.odometer ? `${Number(a.odometer)}${a.odometer_at ? ` (${formatDate(a.odometer_at)})` : ""}` : "—" },
              { label: t("garage.workshop.nextService"), value: a.next_service_date || a.next_service_odometer ? [a.next_service_date ? formatDate(a.next_service_date) : null, a.next_service_odometer ? Number(a.next_service_odometer) : null].filter(Boolean).join(" · ") : "—" },
              { label: t("items.notes"), value: a.notes ?? "—" },
            ]} />
          </Card>
          <CustomFields entityType="jobs.asset" entityId={a.id} canEdit={canManage} />
          <Attachments entityType="jobs.asset" entityId={a.id} title={t("garage.photos.itemTitle")} />
        </aside>
      </div>
      {editing && <ItemDrawer asset={a} onClose={() => setEditing(false)} />}
    </>
  );
}
