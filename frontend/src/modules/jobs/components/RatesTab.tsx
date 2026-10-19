import { useEffect, useState } from "react";

import { api, Alert, Button, Card, ErrorState, Field, FormGrid, NumberInput, Select, Skeleton, Switch, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { useJobSettings } from "../hooks";
import { ProductPicker } from "./pickers";

/** Labour rate, the two service items jobs are invoiced under, the warranty and the "ready" message. */
export function RatesTab({ companyId, currency }: { companyId: string; currency: string | undefined }) {
  const { t } = useTranslation("jobs");
  const qc = useQueryClient();
  const settings = useJobSettings(companyId);
  const [rate, setRate] = useState("");
  const [labour, setLabour] = useState("");
  const [parts, setParts] = useState("");
  const [warranty, setWarranty] = useState("0");
  const [valid, setValid] = useState("14");
  const [tell, setTell] = useState(true);
  const [fees, setFees] = useState("");
  const [unit, setUnit] = useState("km");
  const [extra, setExtra] = useState("warn");
  const [release, setRelease] = useState("off");
  const [photos, setPhotos] = useState("warn");
  const [storage, setStorage] = useState("0");
  const [grace, setGrace] = useState("7");
  const [remind, setRemind] = useState(false);
  const [remindDays, setRemindDays] = useState("14");
  const [pickup, setPickup] = useState("0");
  const s = settings.data;
  useEffect(() => {
    if (!s) return;
    setRate(s.default_labour_rate); setLabour(s.labour_product_id ?? ""); setParts(s.parts_product_id ?? "");
    setWarranty(String(s.default_warranty_days)); setValid(String(s.estimate_valid_days)); setTell(s.tell_customer_when_ready);
    setFees(s.fees_product_id ?? ""); setUnit(s.odometer_unit); setExtra(s.unapproved_work); setRelease(s.release_unpaid); setPhotos(s.required_photos);
    setStorage(String(Number(s.storage_fee_per_day))); setGrace(String(s.storage_grace_days)); setRemind(s.remind_service_due); setRemindDays(String(s.service_reminder_days)); setPickup(String(s.ready_reminder_days));
  }, [s]);
  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.PATCH("/api/v1/jobs/settings", { params: { query: { company_id: companyId } }, body: {
      default_labour_rate: rate || "0", labour_product_id: labour || null, parts_product_id: parts || null,
      default_warranty_days: Number(warranty) || 0, estimate_valid_days: Math.max(Number(valid) || 14, 1), tell_customer_when_ready: tell,
      fees_product_id: fees || null, odometer_unit: unit as "km" | "mi", unapproved_work: extra as "off" | "warn" | "block", release_unpaid: release as "off" | "warn" | "block",
      required_photos: photos as "off" | "warn" | "block", storage_fee_per_day: storage || "0", storage_grace_days: Number(grace) || 0, remind_service_due: remind,
      service_reminder_days: Math.max(Number(remindDays) || 14, 1), ready_reminder_days: Number(pickup) || 0 } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["jobs"] }); toast(t("rates.saved"), "ok"); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  if (settings.error) return <ErrorState title={t("rates.loadFailed")} message={settings.error.message} onRetry={() => void settings.refetch()} />;
  if (!s) return <Skeleton className="h-64" />;
  return (
    <div className="space-y-4">
    <Card title={t("rates.title")}>
      <div className="space-y-4">
        {!s.invoicing_available && <Alert tone="warn">{t("rates.noInvoicing")}</Alert>}
        <FormGrid>
          <Field label={t("rates.labourRate")} hint={t("rates.labourRateHint", { currency: currency ?? "" })}><NumberInput value={rate} onChange={setRate} /></Field>
          <Field label={t("rates.warranty")} hint={t("rates.warrantyHint")}><NumberInput value={warranty} onChange={(v) => setWarranty(v.replace(/\./g, ""))} /></Field>
          <Field label={t("rates.valid")} hint={t("rates.validHint")}><NumberInput value={valid} onChange={(v) => setValid(v.replace(/\./g, ""))} /></Field>
        </FormGrid>
        <Field label={t("rates.labourItem")} hint={t("rates.itemHint")}><ProductPicker services value={labour} onChange={setLabour} /></Field>
        <Field label={t("rates.partsItem")} hint={t("rates.itemHint")}><ProductPicker services value={parts} onChange={setParts} /></Field>
        <Field label={t("garage.rates.feesItem")} hint={t("garage.rates.feesItemHint")}><ProductPicker services value={fees} onChange={setFees} /></Field>
        <div className="flex items-center gap-2 text-sm"><Switch checked={tell} onChange={setTell} label={t("rates.tell")} /><span>{t("rates.tell")}</span></div>
        <p className="text-xs text-muted">{t("rates.tellHint")}</p>
        <div className="flex justify-end"><Button loading={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button></div>
      </div>
    </Card>
    <Card title={t("garage.rates.rulesTitle")} description={t("garage.rates.rulesHint")}>
      <div className="space-y-4">
        <FormGrid>
          {([["unapproved", extra, setExtra, "unapprovedWork"], ["release", release, setRelease, "releaseUnpaid"], ["photos", photos, setPhotos, "requiredPhotos"]] as const).map(([key, value, set, label]) => (
            <Field key={key} label={t(`garage.rates.${label}`)} hint={t(`garage.rates.${label}Hint`)}>
              <Select value={value} onChange={(e) => set(e.target.value)}>{(["off", "warn", "block"] as const).map((m) => <option key={m} value={m}>{t(`garage.rates.mode.${m}`)}</option>)}</Select>
            </Field>
          ))}
          <Field label={t("garage.rates.odometerUnit")}><Select value={unit} onChange={(e) => setUnit(e.target.value)}><option value="km">km</option><option value="mi">mi</option></Select></Field>
          <Field label={t("garage.rates.storageFee")} hint={t("garage.rates.storageFeeHint", { currency: currency ?? "" })}><NumberInput value={storage} onChange={setStorage} /></Field>
          <Field label={t("garage.rates.storageGrace")}><NumberInput value={grace} onChange={(v) => setGrace(v.replace(/\./g, ""))} /></Field>
          <Field label={t("garage.rates.pickupReminder")} hint={t("garage.rates.pickupReminderHint")}><NumberInput value={pickup} onChange={(v) => setPickup(v.replace(/\./g, ""))} /></Field>
        </FormGrid>
        <div className="flex items-center gap-2 text-sm"><Switch checked={remind} onChange={setRemind} label={t("garage.rates.serviceReminders")} /><span>{t("garage.rates.serviceReminders")}</span></div>
        {remind && <Field label={t("garage.rates.serviceDays")} hint={t("garage.rates.serviceDaysHint")}><NumberInput value={remindDays} onChange={(v) => setRemindDays(v.replace(/\./g, ""))} /></Field>}
        <div className="flex justify-end"><Button loading={save.isPending} onClick={() => save.mutate()}>{t("common.save")}</Button></div>
      </div>
    </Card>
    </div>
  );
}
