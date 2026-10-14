import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api, Button, DataTable, Drawer, Field, formatDate, PageHeader, Pager, Select, toast, unwrap, useCan, useFormState, useMutation, usePagedList, useQueryClient, useTranslation,
} from "@/sdk";

import { DocStatus, STATUS_FILTERS } from "../components/DocStatus";
import { LinesEditor } from "../components/LinesEditor";
import { LocationSelect } from "../components/LocationSelect";
import { duplicateProducts, filledLines, newLine } from "../logic";
import { CompanyField, useFormCompany, useLocations } from "../lookups";

/** Transfers of stock between two locations of a company, through in-transit. */
export default function TransfersPage() {
  const { t } = useTranslation("inventory");
  const canTransfer = useCan("stock.transfer");
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState("");
  const [locationId, setLocationId] = useState("");
  const locations = useLocations();
  const list = usePagedList(["inv-transfers", status, locationId], (limit, offset) =>
    unwrap(api.GET("/api/v1/inventory/transfers", { params: { query: { status: status || undefined, location_id: locationId || undefined, limit, offset } } })));
  const code = (id: string) => locations.data?.find((l) => l.id === id)?.code ?? "—";
  const newButton = canTransfer ? <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newTransfer")}</Button> : undefined;

  return (
    <>
      <PageHeader title={t("transfers")} description={t("transfersHint")} actions={newButton} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(x) => x.id}
        rowHref={(x) => `/stock/transfers/${x.id}`}
        toolbar={
          <>
            <Select aria-label={t("status")} className="w-44" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>
              {STATUS_FILTERS.transfers.map((s) => <option key={s} value={s}>{t(`docStatus.${s}`)}</option>)}
            </Select>
            <div className="w-52"><LocationSelect label={t("location")} value={locationId} onChange={setLocationId} allLabel={t("allLocations")} /></div>
          </>
        }
        empty={{ title: t("noTransfers"), hint: t("noTransfersHint"), action: newButton }}
        columns={[
          { header: t("number"), cell: (x) => <span className="font-mono text-xs font-medium">{x.number}</span> },
          { header: t("from"), cell: (x) => code(x.from_location_id) },
          { header: t("to"), cell: (x) => code(x.to_location_id) },
          { header: t("status"), cell: (x) => <DocStatus status={x.status} /> },
          { header: t("dispatchedOn"), hideBelow: "md", cell: (x) => formatDate(x.dispatched_at) },
          { header: t("receivedOn"), hideBelow: "lg", cell: (x) => formatDate(x.received_at) },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <NewTransfer open={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function NewTransfer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation("inventory");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const f = useFormState({ company_id: "", from: "", to: "" });
  const { companyId, companies } = useFormCompany(f.values.company_id);
  const [lines, setLines] = useState([newLine()]);
  const filled = filledLines(lines);
  const duplicates = duplicateProducts(lines);
  const ready = !!f.values.from && !!f.values.to && f.values.from !== f.values.to && filled.length > 0 && duplicates.length === 0;

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/inventory/transfers", { body: {
      company_id: companyId, from_location_id: f.values.from, to_location_id: f.values.to,
      lines: filled.map((l) => ({ product_id: l.productId, quantity: l.qty })) } })),
    onSuccess: (x) => {
      void qc.invalidateQueries({ queryKey: ["inv-transfers"] });
      toast(t("draftSaved", { number: x.number }), "ok");
      f.reset(); setLines([newLine()]); onClose(); navigate(`/stock/transfers/${x.id}`);
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (ready) save.mutate(); };
  const places = ["store", "warehouse", "virtual"];

  return (
    <Drawer open={open} onClose={onClose} title={t("newTransfer")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="new-transfer" loading={save.isPending} disabled={!ready}>{t("saveDraft")}</Button></>}>
      <form id="new-transfer" onSubmit={submit} className="space-y-4">
        <CompanyField label={t("company")} value={companyId} onChange={(v) => { f.set("company_id", v); f.set("from", ""); f.set("to", ""); }} companies={companies} />
        <Field label={t("from")} required error={f.error("from_location_id")}>
          <LocationSelect label={t("from")} companyId={companyId} kinds={places} value={f.values.from} onChange={(v) => f.set("from", v)} exclude={f.values.to} />
        </Field>
        <Field label={t("to")} required error={f.error("to_location_id")}>
          <LocationSelect label={t("to")} companyId={companyId} kinds={places} value={f.values.to} onChange={(v) => f.set("to", v)} exclude={f.values.from} />
        </Field>
        <LinesEditor lines={lines} onChange={setLines} />
        {duplicates.length > 0 && <p role="alert" className="text-sm text-bad">{t("duplicateProduct")}</p>}
        {f.error("lines") && <p role="alert" className="text-sm text-bad">{f.error("lines")}</p>}
      </form>
    </Drawer>
  );
}
