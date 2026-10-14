import { Plus } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  api, Button, DataTable, Drawer, Field, formatDate, PageHeader, Pager, Select, Textarea, toast, unwrap, useCan, useFormState, useMutation, usePagedList, useQueryClient, useTranslation,
} from "@/sdk";

import { DocStatus, STATUS_FILTERS } from "../components/DocStatus";
import { LinesEditor } from "../components/LinesEditor";
import { LocationSelect } from "../components/LocationSelect";
import { duplicateProducts, filledLines, newLine, signedQty } from "../logic";
import { CompanyField, useFormCompany, useLocations, useReasons } from "../lookups";

/** Stock adjustments: write one as a draft, then submit it (it posts at once or goes to an approver). */
export default function AdjustmentsPage() {
  const { t } = useTranslation("inventory");
  const canAdjust = useCan("stock.adjust");
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState("");
  const [locationId, setLocationId] = useState("");
  const locations = useLocations();
  const reasons = useReasons("stock_adjustment");
  const list = usePagedList(["inv-adjustments", status, locationId], (limit, offset) =>
    unwrap(api.GET("/api/v1/inventory/adjustments", { params: { query: { status: status || undefined, location_id: locationId || undefined, limit, offset } } })));
  const newButton = canAdjust ? <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newAdjustment")}</Button> : undefined;

  return (
    <>
      <PageHeader title={t("adjustments")} description={t("adjustmentsHint")} actions={newButton} />
      <DataTable
        rows={list.rows} loading={list.query.isLoading} error={list.query.error?.message} onRetry={() => void list.query.refetch()} rowKey={(a) => a.id}
        rowHref={(a) => `/stock/adjustments/${a.id}`}
        toolbar={
          <>
            <Select aria-label={t("status")} className="w-44" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">{t("allStatuses")}</option>
              {STATUS_FILTERS.adjustments.map((s) => <option key={s} value={s}>{t(`docStatus.${s}`)}</option>)}
            </Select>
            <div className="w-52"><LocationSelect label={t("location")} value={locationId} onChange={setLocationId} allLabel={t("allLocations")} /></div>
          </>
        }
        empty={{ title: t("noAdjustments"), hint: t("noAdjustmentsHint"), action: newButton }}
        columns={[
          { header: t("number"), cell: (a) => <span className="font-mono text-xs font-medium">{a.number}</span> },
          { header: t("location"), hideBelow: "sm", cell: (a) => locations.data?.find((l) => l.id === a.location_id)?.code ?? "—" },
          { header: t("reason"), hideBelow: "md", cell: (a) => reasons.data?.find((r) => r.id === a.reason_code_id)?.label ?? "—" },
          { header: t("status"), cell: (a) => <DocStatus status={a.status} /> },
          { header: t("postedOn"), hideBelow: "lg", cell: (a) => formatDate(a.posted_at) },
        ]}
        footer={<Pager page={list.page} onPage={list.setPage} hasNext={list.hasNext} count={list.rows?.length ?? 0} />}
      />
      <NewAdjustment open={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function NewAdjustment({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation("inventory");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const f = useFormState({ company_id: "", location_id: "", reason_code_id: "", note: "" });
  const { companyId, companies } = useFormCompany(f.values.company_id);
  const reasons = useReasons("stock_adjustment", open);
  const [lines, setLines] = useState([newLine()]);
  const filled = filledLines(lines);
  const duplicates = duplicateProducts(lines);
  const reasonId = f.values.reason_code_id || reasons.data?.[0]?.id || "";
  const ready = !!f.values.location_id && !!reasonId && filled.length > 0 && duplicates.length === 0;

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/inventory/adjustments", { body: {
      company_id: companyId, location_id: f.values.location_id, reason_code_id: reasonId, note: f.values.note.trim() || null,
      lines: filled.map((l) => ({ product_id: l.productId, qty_change: signedQty(l) })) } })),
    onSuccess: (a) => {
      void qc.invalidateQueries({ queryKey: ["inv-adjustments"] });
      toast(t("draftSaved", { number: a.number }), "ok");
      f.reset(); setLines([newLine()]); onClose(); navigate(`/stock/adjustments/${a.id}`);
    },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); if (ready) save.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={t("newAdjustment")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="new-adjustment" loading={save.isPending} disabled={!ready}>{t("saveDraft")}</Button></>}>
      <form id="new-adjustment" onSubmit={submit} className="space-y-4">
        <CompanyField label={t("company")} value={companyId} onChange={(v) => { f.set("company_id", v); f.set("location_id", ""); }} companies={companies} />
        <Field label={t("location")} required error={f.error("location_id")}>
          <LocationSelect label={t("location")} companyId={companyId} kinds={["store", "warehouse", "virtual"]} value={f.values.location_id} onChange={(v) => f.set("location_id", v)} />
        </Field>
        <Field label={t("reason")} required error={f.error("reason_code_id")}>
          <Select value={reasonId} onChange={(e) => f.set("reason_code_id", e.target.value)}>{(reasons.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}</Select>
        </Field>
        <Field label={t("note")} error={f.error("note")}><Textarea rows={2} {...f.bind("note")} /></Field>
        <LinesEditor lines={lines} onChange={setLines} signed />
        {duplicates.length > 0 && <p role="alert" className="text-sm text-bad">{t("duplicateProduct")}</p>}
        {f.error("lines") && <p role="alert" className="text-sm text-bad">{f.error("lines")}</p>}
      </form>
    </Drawer>
  );
}
