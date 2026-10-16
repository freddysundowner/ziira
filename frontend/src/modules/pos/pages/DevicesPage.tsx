import { Ban, CheckCircle2, KeyRound, Plus, Store } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";

import {
  api, Alert, Button, ConfirmDialog, DataTable, Drawer, Field, formatDate, FormGrid, Input, Menu, Modal, PageHeader, Schemas, Select, StatusBadge, toast,
  unwrap, useCan, useFormState, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { useBranches, useDevices, useLocations } from "../hooks";
import { defaultStoreId } from "../lib";

type Device = Schemas["DeviceOut"];

/** The tills (tablets, phones, counters) that may sell: register one, block a lost one, give one a new key. */
export default function DevicesPage() {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const canManage = useCan("devices.manage");
  const devices = useDevices();
  const { nameOf } = useBranches();
  const locations = useLocations(null);
  const [creating, setCreating] = useState(false);
  const [toggle, setToggle] = useState<Device | null>(null);
  const [rotate, setRotate] = useState<Device | null>(null);
  const [storeOf, setStoreOf] = useState<Device | null>(null);
  const [shownKey, setShownKey] = useState<{ name: string; key: string } | null>(null);
  const locationName = (id: string | null) => (id ? locations.data?.find((l) => l.id === id)?.name ?? "—" : "—");

  const setStatus = useMutation({
    mutationFn: (d: Device) => unwrap(api.PATCH("/api/v1/pos/devices/{device_id}/status", { params: { path: { device_id: d.id } }, body: { status: d.status === "active" ? "blocked" : "active" } })),
    onSuccess: (d) => { void qc.invalidateQueries({ queryKey: ["pos-devices"] }); toast(t(d.status === "active" ? "deviceUnblocked" : "deviceBlocked", { name: d.name }), "ok"); setToggle(null); },
  });
  const newKey = useMutation({
    mutationFn: (d: Device) => unwrap(api.POST("/api/v1/pos/devices/{device_id}/rotate-key", { params: { path: { device_id: d.id } } })),
    onSuccess: (d) => { void qc.invalidateQueries({ queryKey: ["pos-devices"] }); setRotate(null); setShownKey({ name: d.name, key: d.key }); },
  });

  return (
    <>
      <PageHeader title={t("devices")} description={t("devicesHint")} actions={canManage && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />{t("newDevice")}</Button>} />
      <DataTable
        rows={devices.data} loading={devices.isLoading} error={devices.error?.message} onRetry={() => void devices.refetch()} rowKey={(d) => d.id}
        searchText={(d) => `${d.name} ${d.code}`} searchPlaceholder={t("searchDevices")}
        empty={{ title: t("noDevices"), hint: t("noDevicesHint"), action: canManage ? <Button onClick={() => setCreating(true)}>{t("newDevice")}</Button> : undefined }}
        columns={[
          { header: t("name"), sortValue: (d) => d.name, cell: (d) => <span className="font-medium">{d.name}</span> },
          { header: t("code"), cell: (d) => <span className="font-mono text-xs">{d.code}</span> },
          { header: t("branch"), hideBelow: "md", cell: (d) => nameOf(d.branch_id) },
          { header: t("store"), hideBelow: "lg", cell: (d) => locationName(d.location_id) },
          { header: t("lastSync"), hideBelow: "lg", cell: (d) => formatDate(d.last_sync_at, true) },
          { header: t("status"), cell: (d) => <StatusBadge status={d.status} /> },
          ...(canManage ? [{
            header: "", align: "right" as const, cell: (d: Device) => (
              <Menu label={t("actions")} trigger={<span className="rounded-lg px-2 py-1 text-muted hover:bg-sunken">•••</span>} items={[
                d.status === "active"
                  ? { label: t("blockDevice"), icon: <Ban className="h-4 w-4" />, danger: true, onSelect: () => setToggle(d) }
                  : { label: t("unblockDevice"), icon: <CheckCircle2 className="h-4 w-4" />, onSelect: () => setToggle(d) },
                { label: t("changeStore"), icon: <Store className="h-4 w-4" />, onSelect: () => setStoreOf(d) },
                { label: t("newKey"), icon: <KeyRound className="h-4 w-4" />, onSelect: () => setRotate(d) },
              ]} />
            ),
          }] : []),
        ]}
      />
      <NewDevice open={creating} onClose={() => setCreating(false)} onCreated={(name, key) => setShownKey({ name, key })} />
      <ConfirmDialog open={Boolean(toggle)} onClose={() => setToggle(null)} busy={setStatus.isPending} danger={toggle?.status === "active"}
        title={toggle?.status === "active" ? t("blockDevice") : t("unblockDevice")}
        message={toggle?.status === "active" ? t("blockAsk", { name: toggle.name }) : t("unblockAsk", { name: toggle?.name })}
        confirmLabel={toggle?.status === "active" ? t("blockDevice") : t("unblockDevice")} onConfirm={() => toggle && setStatus.mutate(toggle)} />
      <ConfirmDialog open={Boolean(rotate)} onClose={() => setRotate(null)} busy={newKey.isPending} danger title={t("newKey")}
        message={t("newKeyAsk", { name: rotate?.name })} confirmLabel={t("newKey")} onConfirm={() => rotate && newKey.mutate(rotate)} />
      <ChangeStore device={storeOf} onClose={() => setStoreOf(null)} />
      <KeyModal shown={shownKey} onClose={() => setShownKey(null)} />
    </>
  );
}

function NewDevice({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (name: string, key: string) => void }) {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const { branches } = useBranches();
  const f = useFormState({ branch_id: "", code: "", name: "", location_id: "" });
  const branchId = f.values.branch_id || branches[0]?.id || "";
  const locations = useQuery({ enabled: open && Boolean(branchId), retry: false, queryKey: ["inventory-locations", branchId], queryFn: () => unwrap(api.GET("/api/v1/inventory/locations", { params: { query: { branch_id: branchId } } })) });

  const stores = locations.data?.filter((l) => l.is_active);
  const noStores = Boolean(stores) && stores?.length === 0;
  const storeId = f.values.location_id || defaultStoreId(stores);

  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/pos/devices", { body: { branch_id: branchId, code: f.values.code.trim(), name: f.values.name.trim(), location_id: storeId || null } })),
    onSuccess: (d) => { void qc.invalidateQueries({ queryKey: ["pos-devices"] }); toast(t("deviceCreated", { name: d.name }), "ok"); f.reset(); onClose(); onCreated(d.name, d.key); },
    onError: (e) => { f.fail(e); toast((e as Error).message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={t("newDevice")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="new-device" loading={create.isPending} disabled={!branchId || noStores}>{t("save")}</Button></>}>
      <form id="new-device" onSubmit={submit} className="space-y-4">
        <Field label={t("name")} required error={f.error("name")} hint={t("deviceNameHint")}><Input {...f.bind("name")} required autoFocus maxLength={100} /></Field>
        <FormGrid>
          <Field label={t("code")} required error={f.error("code")} hint={t("deviceCodeHint")}><Input {...f.bind("code")} required maxLength={8} className="font-mono uppercase" /></Field>
          <Field label={t("branch")} required error={f.error("branch_id")}>
            <Select value={branchId} onChange={(e) => { f.set("branch_id", e.target.value); f.set("location_id", ""); }}>
              {branches.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </Select>
          </Field>
        </FormGrid>
        {noStores && (
          <Alert tone="warn">{t("noStoreYet")} <Link className="font-medium underline" to="/stock/locations">{t("addStoreLink")}</Link></Alert>
        )}
        {stores && stores.length > 0 && (
          <Field label={t("store")} required hint={t("storeHint")} error={f.error("location_id")}>
            <Select value={storeId} onChange={(e) => f.set("location_id", e.target.value)} required>
              {stores.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
            </Select>
          </Field>
        )}
      </form>
    </Drawer>
  );
}

/** Change the store a till's sales take stock from (the server refuses while a till is open on it). */
function ChangeStore({ device, onClose }: { device: Device | null; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const qc = useQueryClient();
  const locations = useLocations(device?.branch_id, Boolean(device));
  const stores = locations.data?.filter((l) => l.is_active);
  const [picked, setPicked] = useState("");
  const current = picked || device?.location_id || defaultStoreId(stores);
  const save = useMutation({
    mutationFn: () => unwrap(api.PATCH("/api/v1/pos/devices/{device_id}", { params: { path: { device_id: device?.id ?? "" } }, body: { location_id: current } })),
    onSuccess: (d) => { void qc.invalidateQueries({ queryKey: ["pos-devices"] }); toast(t("storeChanged", { name: d.name }), "ok"); setPicked(""); onClose(); },
  });
  return (
    <Modal open={Boolean(device)} onClose={onClose} title={t("changeStoreOf", { name: device?.name })} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button loading={save.isPending} disabled={!current} onClick={() => save.mutate()}>{t("save")}</Button></>}>
      <Field label={t("store")} hint={t("changeStoreHint")}>
        <Select value={current} onChange={(e) => setPicked(e.target.value)}>
          {(stores ?? []).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
        </Select>
      </Field>
    </Modal>
  );
}

/** The key is shown once: the only moment it can be copied. */
function KeyModal({ shown, onClose }: { shown: { name: string; key: string } | null; onClose: () => void }) {
  const { t } = useTranslation("pos");
  const copy = () => navigator.clipboard?.writeText(shown?.key ?? "").then(() => toast(t("keyCopied"), "ok"), () => undefined);
  return (
    <Modal open={Boolean(shown)} onClose={onClose} title={t("deviceKey", { name: shown?.name })} size="sm"
      footer={<><Button variant="secondary" onClick={copy}>{t("copy")}</Button><Button onClick={onClose}>{t("keySaved")}</Button></>}>
      <div className="space-y-3">
        <Alert tone="warn">{t("keyOnce")}</Alert>
        <code className="block break-all rounded-lg bg-sunken p-3 font-mono text-sm">{shown?.key}</code>
      </div>
    </Modal>
  );
}
