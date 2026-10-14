import { Plus, X } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api, Button, Checkbox, DataTable, Drawer, Field, formatDate, PageHeader, Pager, Select, toast, unwrap, useCan, useFormState, useMutation, usePagedList, useQueryClient, useTranslation,
} from "@/sdk";

import { DocStatus, STATUS_FILTERS } from "../components/DocStatus";
import { LocationSelect } from "../components/LocationSelect";
import { CompanyField, ProductPicker, useFormCompany, useLocations } from "../lookups";

/** Stock counts: take a snapshot of a location, enter what is on the shelf, review the differences, post. */
export default function CountsPage() {
  const { t } = useTranslation("inventory");
  const canCount = useCan("stock.count");
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState("");
  const [locationId, setLocationId] = useState("");
  const locations = useLocations();
  const list = usePagedList(["inv-counts", status, locationId], (limit, offset) =>
    unwrap(api.GET("/api/v1/inventory/counts", { params: { query: { status: status || undefined, location_id: locationId || undefined, limit, offset } } })));
  const newButton = canCount ? <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newCount")}</Button> : undefined;

  return (
    <>
      <PageHeader title={t("counts")} description={t("countsHint")} actions={newButton} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(c) => c.id}
        rowHref={(c) => `/stock/counts/${c.id}`}
        toolbar={
          <>
            <Select aria-label={t("status")} className="w-44" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>
              {STATUS_FILTERS.counts.map((s) => <option key={s} value={s}>{t(`docStatus.${s}`)}</option>)}
            </Select>
            <div className="w-52"><LocationSelect label={t("location")} value={locationId} onChange={setLocationId} allLabel={t("allLocations")} /></div>
          </>
        }
        empty={{ title: t("noCounts"), hint: t("noCountsHint"), action: newButton }}
        columns={[
          { header: t("number"), cell: (c) => <span className="font-mono text-xs font-medium">{c.number}</span> },
          { header: t("location"), hideBelow: "sm", cell: (c) => locations.data?.find((l) => l.id === c.location_id)?.name ?? "—" },
          { header: t("status"), cell: (c) => <DocStatus status={c.status} /> },
          { header: t("startedOn"), hideBelow: "md", cell: (c) => formatDate(c.snapshot_at, true) },
          { header: t("postedOn"), hideBelow: "lg", cell: (c) => formatDate(c.posted_at) },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <NewCount open={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function NewCount({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation("inventory");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const f = useFormState({ company_id: "", location_id: "" });
  const { companyId, companies } = useFormCompany(f.values.company_id);
  const [subset, setSubset] = useState(false);
  const [picked, setPicked] = useState<{ id: string; name: string }[]>([]);
  const ready = !!f.values.location_id && (!subset || picked.length > 0);

  const start = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/inventory/counts", { body: {
      company_id: companyId, location_id: f.values.location_id, product_ids: subset ? picked.map((p) => p.id) : null } })),
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ["inv-counts"] });
      toast(t("countStarted", { number: c.number }), "ok");
      f.reset(); setSubset(false); setPicked([]); onClose(); navigate(`/stock/counts/${c.id}`);
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (ready) start.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={t("newCount")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="new-count" loading={start.isPending} disabled={!ready}>{t("startCount")}</Button></>}>
      <form id="new-count" onSubmit={submit} className="space-y-4">
        <p className="text-sm text-muted">{t("startCountHint")}</p>
        <CompanyField label={t("company")} value={companyId} onChange={(v) => { f.set("company_id", v); f.set("location_id", ""); }} companies={companies} />
        <Field label={t("location")} required error={f.error("location_id")}>
          <LocationSelect label={t("location")} companyId={companyId} kinds={["store", "warehouse", "virtual"]} value={f.values.location_id} onChange={(v) => f.set("location_id", v)} />
        </Field>
        <Checkbox label={t("onlySome")} checked={subset} onChange={(e) => setSubset(e.target.checked)} />
        {subset && (
          <div className="space-y-2">
            <ProductPicker value="" placeholder={t("addProduct")} onChange={(id, name) => { if (id && !picked.some((p) => p.id === id)) setPicked([...picked, { id, name }]); }} />
            <div className="flex flex-wrap gap-1.5">
              {picked.map((p) => (
                <span key={p.id} className="inline-flex items-center gap-1 rounded-full bg-sunken px-2.5 py-1 text-xs">
                  {p.name}
                  <button type="button" aria-label={t("removeLine")} onClick={() => setPicked(picked.filter((x) => x.id !== p.id))}><X className="h-3 w-3" /></button>
                </span>
              ))}
            </div>
          </div>
        )}
      </form>
    </Drawer>
  );
}
