import { useState } from "react";
import { Link } from "react-router-dom";

import {
  Alert, api, Button, Card, ConfirmDialog, Field, FormGrid, Input, PageHeader, toast, today, unwrap, useCurrency, useFormState, useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import { LinesEditor } from "../components/LinesEditor";
import { LocationSelect } from "../components/LocationSelect";
import { duplicateProducts, filledLines, newLine } from "../logic";
import { CompanyField, useFormCompany, useLocations } from "../lookups";

/** Record the stock a location already held when the business started using the system (once per product and location). */
export default function OpeningStockPage() {
  const { t } = useTranslation("inventory");
  const qc = useQueryClient();
  const f = useFormState({ company_id: "", location_id: "", business_date: today() });
  const { companyId, companies } = useFormCompany(f.values.company_id);
  const currency = useCurrency(companyId);
  const [lines, setLines] = useState([newLine()]);
  const [confirming, setConfirming] = useState(false);
  const [posted, setPosted] = useState<number | null>(null);

  const locations = useLocations();
  const places = (locations.data ?? []).filter((l) => l.is_active && l.company_id === companyId && ["store", "warehouse", "virtual"].includes(l.kind));
  const noPlaces = locations.isSuccess && places.length === 0;
  const locationId = f.values.location_id || (places.length === 1 ? places[0]?.id ?? "" : "");

  const filled = filledLines(lines);
  const missingCost = filled.some((l) => l.unitCost === "");
  const duplicates = duplicateProducts(lines);
  const ready = !!locationId && filled.length > 0 && !missingCost && duplicates.length === 0;

  const post = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/inventory/opening-stock", { body: {
      company_id: companyId, location_id: locationId, business_date: f.values.business_date || null,
      lines: filled.map((l) => ({ product_id: l.productId, quantity: l.qty, unit_cost: l.unitCost, batch_no: l.batchNo.trim() || null, expiry_date: l.expiry || null })) } })),
    onSuccess: (moves) => {
      void qc.invalidateQueries({ queryKey: ["inv-balances"] });
      void qc.invalidateQueries({ queryKey: ["inv-range-balances"] });
      void qc.invalidateQueries({ queryKey: ["inv-movements"] });
      toast(t("openingPosted", { count: moves.length }), "ok");
      setPosted(moves.length);
      setLines([newLine()]);
      setConfirming(false);
    },
    onError: (e) => { f.fail(e); setConfirming(false); toast((e as Error).message, "bad"); },
  });

  return (
    <>
      <PageHeader back={{ to: "/stock", label: t("stock") }} title={t("openingStock")} description={t("openingHint")} />
      {posted !== null && (
        <Alert tone="ok" className="mb-4">{t("openingPosted", { count: posted })} <Link className="underline" to="/stock">{t("viewStock")}</Link></Alert>
      )}
      {noPlaces && (
        <Alert tone="warn" className="mb-4">{t("noLocationYet")} <Link className="font-medium underline" to="/stock/locations">{t("addLocationLink")}</Link></Alert>
      )}
      <form onSubmit={(e) => { e.preventDefault(); if (ready) setConfirming(true); }} className="space-y-4">
        <Card>
          <FormGrid>
            <CompanyField label={t("company")} value={companyId} onChange={(v) => { f.set("company_id", v); f.set("location_id", ""); }} companies={companies} />
            <Field label={t("location")} required error={f.error("location_id")}>
              <LocationSelect label={t("location")} companyId={companyId} kinds={["store", "warehouse", "virtual"]} value={locationId} onChange={(v) => f.set("location_id", v)} />
            </Field>
            <Field label={t("asAt")} error={f.error("business_date")} hint={t("asAtHint")}><Input type="date" {...f.bind("business_date")} /></Field>
          </FormGrid>
        </Card>
        <Card title={t("products")} description={t("openingCostHint", { currency: currency ?? "" })}>
          <LinesEditor lines={lines} onChange={setLines} opening />
          {duplicates.length > 0 && <p role="alert" className="mt-3 text-sm text-bad">{t("duplicateProduct")}</p>}
          {f.error("lines") && <p role="alert" className="mt-3 text-sm text-bad">{f.error("lines")}</p>}
        </Card>
        <div className="flex justify-end"><Button type="submit" disabled={!ready} loading={post.isPending}>{t("postOpening")}</Button></div>
      </form>
      <ConfirmDialog open={confirming} onClose={() => setConfirming(false)} busy={post.isPending} onConfirm={() => post.mutate()}
        title={t("postOpening")} confirmLabel={t("postOpening")} message={t("openingAsk", { count: filled.length })} />
    </>
  );
}
