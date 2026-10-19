import { useEffect, useState } from "react";

import { api, Button, Drawer, Field, Input, Select, Switch, Textarea, unwrap, useFormState, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { type EntityRow, type FieldRow, KINDS, keyFromLabel, type Kind, parseChoices } from "./lib";

/** Add a custom field to a record type, or change one (its key and kind stay as they were made). */
export default function FieldDrawer({ entity, field, open, onClose }: { entity: EntityRow | null; field: FieldRow | null; open: boolean; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const f = useFormState({ label: "", key: "", kind: "text" as Kind, choices: "" });
  const [required, setRequired] = useState(false);
  const [searchable, setSearchable] = useState(false);
  const [keyEdited, setKeyEdited] = useState(false);
  const editing = field !== null;

  useEffect(() => {
    if (!open) return;
    f.reset();
    setKeyEdited(false);
    if (field) {
      f.set("label", field.label); f.set("key", field.key); f.set("kind", field.kind as Kind); f.set("choices", field.choices.join("\n"));
      setRequired(field.required); setSearchable(field.searchable);
    } else {
      setRequired(false); setSearchable(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when the drawer opens
  }, [open, field]);

  const save = useMutation({
    meta: { silent: true },
    mutationFn: () => {
      const choices = f.values.kind === "choice" ? parseChoices(f.values.choices) : [];
      if (field) {
        return unwrap(api.PATCH("/api/v1/custom-fields/{field_id}", {
          params: { path: { field_id: field.id } },
          body: { label: f.values.label.trim(), required, searchable, ...(field.kind === "choice" ? { choices } : {}) },
        }));
      }
      return unwrap(api.POST("/api/v1/custom-fields", {
        body: { entity_type: entity?.entity_type ?? "", key: f.values.key.trim(), label: f.values.label.trim(), kind: f.values.kind, choices, required, searchable },
      }));
    },
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["custom-fields"] }); onClose(); },
    onError: (e) => f.fail(e),
  });
  const labelMissing = f.values.label.trim() === "";
  const keyMissing = !editing && f.values.key.trim() === "";
  const choiceMissing = f.values.kind === "choice" && parseChoices(f.values.choices).length === 0;

  return (
    <Drawer open={open} onClose={onClose} title={editing ? t("fields.editTitle") : t("fields.addTitle", { record: entity?.label ?? "" })}
      footer={<><Button variant="secondary" onClick={onClose}>{t("fields.cancel")}</Button>
        <Button loading={save.isPending} disabled={labelMissing || keyMissing || choiceMissing} onClick={() => save.mutate()}>{t("fields.save")}</Button></>}>
      <div className="space-y-4">
        <Field label={t("fields.label")} hint={t("fields.labelHint")} error={f.error("label") ?? f.error("body.label")}>
          <Input value={f.values.label} maxLength={80} autoFocus
            onChange={(e) => { f.set("label", e.target.value); if (!editing && !keyEdited) f.set("key", keyFromLabel(e.target.value)); }} />
        </Field>
        {!editing && (
          <Field label={t("fields.key")} hint={t("fields.keyHint")} error={f.error("key") ?? f.error("body.key")}>
            <Input value={f.values.key} maxLength={40} className="font-mono" onChange={(e) => { setKeyEdited(true); f.set("key", e.target.value.toLowerCase()); }} />
          </Field>
        )}
        <Field label={t("fields.kind")} hint={editing ? t("fields.kindFixed") : undefined}>
          <Select value={f.values.kind} disabled={editing} onChange={(e) => f.set("kind", e.target.value as Kind)}>
            {KINDS.map((k) => <option key={k} value={k}>{t(`fields.kinds.${k}`)}</option>)}
          </Select>
        </Field>
        {f.values.kind === "choice" && (
          <Field label={t("fields.choices")} hint={t("fields.choicesHint")} error={f.error("choices")}>
            <Textarea value={f.values.choices} rows={5} onChange={(e) => f.set("choices", e.target.value)} />
          </Field>
        )}
        <div className="flex items-center justify-between gap-4">
          <div><p className="text-sm font-medium">{t("fields.required")}</p><p className="text-xs text-muted">{t("fields.requiredHint")}</p></div>
          <Switch checked={required} onChange={setRequired} label={t("fields.required")} />
        </div>
        {f.values.kind === "text" && (
          <div className="flex items-center justify-between gap-4">
            <div><p className="text-sm font-medium">{t("fields.searchable")}</p><p className="text-xs text-muted">{t("fields.searchableHint")}</p></div>
            <Switch checked={searchable} onChange={setSearchable} label={t("fields.searchable")} />
          </div>
        )}
      </div>
    </Drawer>
  );
}
