import { type FormEvent, useEffect, useState } from "react";

import {
  Alert, api, Button, Checkbox, Drawer, Field, FormGrid, Input, money, NumberInput, Select, Textarea, toast, unwrap, useMutation, useQuery, useTranslation,
} from "@/sdk";

import { useBranch, useRefreshBookings, useResources } from "../hooks";
import type { Offer } from "../types";

/** Make a service bookable (or change it): how long it takes, what it costs, who can do it. */
export function OfferForm({ open, onClose, offer }: { open: boolean; onClose: () => void; offer?: Offer }) {
  const { t } = useTranslation("bookings");
  const refresh = useRefreshBookings();
  const { companyId, branchId, currency } = useBranch();
  const resources = useResources(branchId, true);
  const items = useQuery({
    queryKey: ["bookings", "service-items", companyId], enabled: open && !!companyId,
    queryFn: () => unwrap(api.GET("/api/v1/bookings/service-items", { params: { query: { company_id: companyId } } })),
  });
  const [productId, setProductId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState("appointment");
  const [duration, setDuration] = useState("60");
  const [before, setBefore] = useState("0");
  const [after, setAfter] = useState("0");
  const [price, setPrice] = useState("");
  const [mode, setMode] = useState("any");
  const [capacity, setCapacity] = useState("1");
  const [publicly, setPublicly] = useState(true);
  const [active, setActive] = useState(true);
  const [who, setWho] = useState<string[]>([]);
  const [procStart, setProcStart] = useState("0");
  const [proc, setProc] = useState("0");
  const [depPct, setDepPct] = useState("0");
  const [depAmt, setDepAmt] = useState("0");
  const [recall, setRecall] = useState("");
  const [patch, setPatch] = useState(false);
  const [lateHours, setLateHours] = useState("");
  const [variants, setVariants] = useState<{ label: string; level: string; price: string }[]>([]);
  useEffect(() => {
    if (!open) return;
    setProductId(offer?.product_id ?? ""); setName(offer?.name ?? ""); setDescription(offer?.description ?? ""); setKind(offer?.kind ?? "appointment");
    setDuration(String(offer?.duration_minutes ?? 60)); setBefore(String(offer?.buffer_before_minutes ?? 0)); setAfter(String(offer?.buffer_after_minutes ?? 0));
    setPrice(offer?.price ?? ""); setMode(offer?.resource_mode ?? "any"); setCapacity(String(offer?.capacity ?? 1)); setPublicly(offer?.show_publicly ?? true);
    setActive(offer?.is_active ?? true); setWho(offer?.resource_ids ?? []);
    setProcStart(String(offer?.processing_start_minutes ?? 0)); setProc(String(offer?.processing_minutes ?? 0));
    setDepPct(String(offer?.deposit_percent ?? 0)); setDepAmt(String(offer?.deposit_amount ?? 0)); setRecall(offer?.recall_days == null ? "" : String(offer.recall_days));
    setPatch(offer?.needs_patch_test ?? false); setLateHours(offer?.group_late_cancel_hours == null ? "" : String(offer.group_late_cancel_hours));
    setVariants((offer?.variants ?? []).map((v) => ({ label: v.label, level: v.level ?? "", price: v.price })));
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    meta: { silent: true },
    mutationFn: async () => {
      const shared = {
        description: description.trim() || null, duration_minutes: Number(duration) || 60, buffer_before_minutes: Number(before) || 0,
        buffer_after_minutes: Number(after) || 0, price: price || undefined, resource_mode: mode as "any", capacity: Number(capacity) || 1,
        show_publicly: publicly, resource_ids: who, processing_start_minutes: Number(procStart) || 0, processing_minutes: Number(proc) || 0,
        deposit_percent: depPct || "0", deposit_amount: depAmt || "0", recall_days: recall === "" ? null : Number(recall), needs_patch_test: patch,
        group_late_cancel_hours: lateHours === "" ? null : Number(lateHours),
      };
      const saved = offer
        ? await unwrap(api.PATCH("/api/v1/bookings/offers/{offer_id}", { params: { path: { offer_id: offer.id } }, body: { ...shared, name: name.trim() || undefined, is_active: active, product_id: productId || undefined } }))
        : await unwrap(api.POST("/api/v1/bookings/offers", { body: { ...shared, company_id: companyId, product_id: productId || null, name: name.trim() || null, kind: kind as "appointment" } }));
      if (!isClassKind) {
        await unwrap(api.PUT("/api/v1/bookings/offers/{offer_id}/variants", { params: { path: { offer_id: saved.id } }, body: {
          variants: variants.filter((v) => v.label.trim()).map((v) => ({ label: v.label.trim(), level: v.level.trim() || null, price: v.price || "0", is_active: true })) } }));
      }
      return saved;
    },
    onSuccess: () => { void refresh(); toast(t(offer ? "offers.updated" : "offers.created"), "ok"); onClose(); },
    onError: (e) => toast((e as Error).message, "bad"),
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };
  const isClass = (offer?.kind ?? kind) === "class";
  const isClassKind = isClass;
  const toggle = (id: string) => setWho((w) => (w.includes(id) ? w.filter((x) => x !== id) : [...w, id]));

  return (
    <Drawer open={open} onClose={onClose} title={offer ? t("offers.edit") : t("offers.new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("close")}</Button><Button type="submit" form="offer-form" loading={save.isPending} disabled={!productId && !name.trim()}>{t("save")}</Button></>}>
      <form id="offer-form" onSubmit={submit} className="space-y-4">
        <Field label={t("offers.item")} hint={t("offers.itemHint")}>
          <Select value={productId} onChange={(e) => { setProductId(e.target.value); const it = items.data?.find((i) => i.id === e.target.value); if (it && !name) setName(it.name); if (it?.price && !price) setPrice(it.price); }}>
            <option value="">{t("offers.noItem")}</option>
            {(items.data ?? []).map((i) => <option key={i.id} value={i.id}>{i.name}{i.price ? ` · ${money(i.price, currency)}` : ""}</option>)}
          </Select>
        </Field>
        {items.data?.length === 0 && <Alert tone="info">{t("offers.noItems")}</Alert>}
        <Field label={t("offers.name")} required={!productId}><Input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} /></Field>
        {!offer && (
          <Field label={t("offers.type")}>
            <Select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="appointment">{t("offers.typeAppointment")}</option>
              <option value="class">{t("offers.typeClass")}</option>
            </Select>
          </Field>
        )}
        <FormGrid cols={3}>
          <Field label={t("offers.duration")}><NumberInput value={duration} onChange={(v) => setDuration(v.split(".")[0] ?? "")} /></Field>
          <Field label={t("offers.bufferBefore")}><NumberInput value={before} onChange={(v) => setBefore(v.split(".")[0] ?? "")} /></Field>
          <Field label={t("offers.bufferAfter")}><NumberInput value={after} onChange={(v) => setAfter(v.split(".")[0] ?? "")} /></Field>
        </FormGrid>
        <p className="-mt-2 text-xs text-muted">{t("offers.bufferHint")}</p>
        <FormGrid>
          <Field label={isClass ? t("offers.pricePerPerson") : t("offers.price")} hint={t("offers.priceHint")}><NumberInput value={price} onChange={setPrice} /></Field>
          {isClass && <Field label={t("offers.capacity")}><NumberInput value={capacity} onChange={(v) => setCapacity(v.split(".")[0] ?? "")} /></Field>}
        </FormGrid>
        {!isClass && (
          <>
            <FormGrid cols={3}>
              <Field label={t("offers.procStart")} hint={t("offers.procHint")}><NumberInput value={procStart} onChange={(v) => setProcStart(v.split(".")[0] ?? "")} /></Field>
              <Field label={t("offers.proc")}><NumberInput value={proc} onChange={(v) => setProc(v.split(".")[0] ?? "")} /></Field>
              <Field label={t("offers.recall")} hint={t("offers.recallHint")}><NumberInput value={recall} onChange={(v) => setRecall(v.split(".")[0] ?? "")} /></Field>
            </FormGrid>
            <FormGrid>
              <Field label={t("offers.depositPercent")} hint={t("offers.depositHint")}><NumberInput value={depPct} onChange={setDepPct} /></Field>
              <Field label={t("offers.depositAmount")}><NumberInput value={depAmt} onChange={setDepAmt} /></Field>
            </FormGrid>
            <Checkbox checked={patch} onChange={(e) => setPatch(e.target.checked)} label={t("offers.patchTest")} />
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium">{t("offers.variants")}</legend>
              <p className="text-xs text-muted">{t("offers.variantsHint")}</p>
              {variants.map((v, i) => (
                <div key={i} className="grid grid-cols-[1fr_7rem_6rem_auto] items-end gap-2">
                  <Input aria-label={t("offers.variantLabel")} placeholder={t("offers.variantLabel")} value={v.label} onChange={(e) => setVariants((x) => x.map((y, j) => (j === i ? { ...y, label: e.target.value } : y)))} maxLength={80} />
                  <Input aria-label={t("offers.variantLevel")} placeholder={t("offers.variantLevel")} value={v.level} onChange={(e) => setVariants((x) => x.map((y, j) => (j === i ? { ...y, level: e.target.value } : y)))} maxLength={40} />
                  <NumberInput aria-label={t("offers.price")} value={v.price} onChange={(val) => setVariants((x) => x.map((y, j) => (j === i ? { ...y, price: val } : y)))} />
                  <Button type="button" variant="ghost" onClick={() => setVariants((x) => x.filter((_, j) => j !== i))}>{t("offers.removeVariant")}</Button>
                </div>
              ))}
              <Button type="button" variant="secondary" onClick={() => setVariants((x) => [...x, { label: "", level: "", price: "" }])}>{t("offers.addVariant")}</Button>
            </fieldset>
          </>
        )}
        {isClass && <Field label={t("offers.lateHours")} hint={t("offers.lateHoursHint")}><NumberInput className="max-w-[10rem]" value={lateHours} onChange={(v) => setLateHours(v.split(".")[0] ?? "")} /></Field>}
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">{t("offers.who")}</legend>
          {(resources.data ?? []).length === 0 && <p className="text-sm text-muted">{t("offers.noResources")}</p>}
          {(resources.data ?? []).map((r) => <div key={r.id}><Checkbox checked={who.includes(r.id)} onChange={() => toggle(r.id)} label={r.name} /></div>)}
        </fieldset>
        {who.length > 1 && !isClass && (
          <Field label={t("offers.mode")}>
            <Select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="any">{t("offers.modeAny")}</option>
              <option value="all">{t("offers.modeAll")}</option>
            </Select>
          </Field>
        )}
        <Field label={t("offers.description")} hint={t("offers.descriptionHint")}><Textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={600} /></Field>
        {!isClass && <Checkbox checked={publicly} onChange={(e) => setPublicly(e.target.checked)} label={t("offers.showPublicly")} />}
        {offer && <Checkbox checked={active} onChange={(e) => setActive(e.target.checked)} label={t("offers.active")} />}
      </form>
    </Drawer>
  );
}
