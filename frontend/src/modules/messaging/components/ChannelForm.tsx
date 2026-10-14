import { type FormEvent, useState } from "react";

import {
  api, Alert, Button, Checkbox, Drawer, Field, Input, NumberInput, Select, toast, unwrap, useMutation, useQueryClient, useTranslation,
} from "@/sdk";

import { buildPayload, type Channel, isComplete, providersFor } from "../providers";

/** Choose the gateway and enter its keys. Saving replaces the channel's old settings; keys are never shown again. */
export default function ChannelForm({ open, channel, companyId, replacing, onClose }: { open: boolean; channel: Channel; companyId: string; replacing: boolean; onClose: () => void }) {
  const { t } = useTranslation("messaging");
  const qc = useQueryClient();
  const options = providersFor(channel);
  const [providerId, setProviderId] = useState(options[0]!.id);
  const [values, setValues] = useState<Record<string, string>>({});
  const [label, setLabel] = useState("");
  const provider = options.find((p) => p.id === providerId)!;
  const set = (name: string, v: string) => setValues((x) => ({ ...x, [name]: v }));

  const save = useMutation({
    mutationFn: () => {
      const { secret, config } = buildPayload(provider, values);
      return unwrap(api.PUT("/api/v1/notifications/channels/{channel}", { params: { path: { channel } }, body: { company_id: companyId, provider: provider.id, secret, config, label: label.trim() || provider.name } }));
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["notification-channels"] }); toast(t("saved"), "ok"); setValues({}); setLabel(""); onClose(); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={t(channel)}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form={`channel-${channel}`} loading={save.isPending} disabled={!isComplete(provider, values)}>{t("save")}</Button></>}>
      <form id={`channel-${channel}`} onSubmit={submit} className="space-y-4" autoComplete="off">
        {replacing && <Alert tone="warn">{t("replaceWarning")}</Alert>}
        <Field label={t("provider")}>
          <Select value={providerId} onChange={(e) => { setProviderId(e.target.value); setValues({}); }}>{options.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>
        </Field>
        {provider.fields.map((f) => {
          const label = `${t(`field.${f.name}`)}${f.where === "secret" ? "" : ""}`;
          const hint = f.where === "secret" ? t("writeOnly") : undefined;
          if (f.kind === "bool") {
            return <Checkbox key={`${provider.id}-${f.name}`} label={t(`field.${f.name}`)} checked={values[f.name] === "true"} onChange={(e) => set(f.name, String(e.target.checked))} />;
          }
          return (
            <Field key={`${provider.id}-${f.name}`} label={label} required={f.required} hint={hint}>
              {f.kind === "number"
                ? <NumberInput value={values[f.name] ?? ""} placeholder={f.placeholder} onChange={(v) => set(f.name, v)} />
                : <Input type={f.kind === "password" ? "password" : "text"} autoComplete="off" value={values[f.name] ?? ""} placeholder={f.placeholder} onChange={(e) => set(f.name, e.target.value)} />}
            </Field>
          );
        })}
        <Field label={t("nameOptional")} hint={t("nameHint")}><Input value={label} maxLength={60} onChange={(e) => setLabel(e.target.value)} /></Field>
        <Alert>{t("untestedNote")}</Alert>
      </form>
    </Drawer>
  );
}
