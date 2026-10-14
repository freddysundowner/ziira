import { type FormEvent, useState } from "react";

import { api, Button, Drawer, Field, Input, Textarea, toast, unwrap, useFormState, useMutation, useQueryClient, useTranslation } from "@/sdk";

const DURATIONS = [1, 4, 24, 72, 168] as const;
type Level = "read" | "full";

/** Gives support access: a reason, read-only or full, and for how long. Read-only is the default. */
export default function NewGrantDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const f = useFormState({ reason: "", note: "" });
  const [level, setLevel] = useState<Level>("read");
  const [hours, setHours] = useState<number>(24);
  const create = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/support/grants", { body: { reason: f.values.reason.trim(), note: f.values.note.trim() || null, level, hours } })),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["support-grants"] }); toast(t("support.created"), "ok"); f.reset(); setLevel("read"); setHours(24); onClose(); },
    onError: (e) => { f.fail(e); toast(e.message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); create.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={t("support.newGrant")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button type="submit" form="new-grant" loading={create.isPending} disabled={!f.values.reason.trim()}>{t("support.create")}</Button></>}>
      <form id="new-grant" onSubmit={submit} className="space-y-5">
        <Field label={t("support.reason")} hint={t("support.reasonHint")} required error={f.error("reason")}><Textarea {...f.bind("reason")} required maxLength={500} autoFocus /></Field>
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium">{t("support.level")}</legend>
          {(["read", "full"] as const).map((l) => (
            <label key={l} className="flex cursor-pointer items-start gap-3 rounded-xl border border-line p-3 has-[:checked]:border-brand has-[:checked]:bg-brand-soft">
              <input type="radio" name="level" className="mt-1" checked={level === l} onChange={() => setLevel(l)} />
              <span><span className="block text-sm font-medium">{t(l === "read" ? "support.levelRead" : "support.levelFull")}</span>
                <span className="block text-xs text-muted">{t(l === "read" ? "support.levelReadHint" : "support.levelFullHint")}</span></span>
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend className="mb-1 text-sm font-medium">{t("support.duration")}</legend>
          <div className="flex flex-wrap gap-2">
            {DURATIONS.map((h) => (
              <button key={h} type="button" aria-pressed={hours === h} onClick={() => setHours(h)}
                className={`rounded-lg border px-3 py-1.5 text-sm ${hours === h ? "border-brand bg-brand-soft text-brand-strong" : "border-line text-muted hover:bg-sunken"}`}>{t(`support.hours${h}`)}</button>
            ))}
          </div>
        </fieldset>
        <Field label={t("support.note")} hint={t("support.noteHint")} error={f.error("note")}><Input {...f.bind("note")} maxLength={1000} /></Field>
      </form>
    </Drawer>
  );
}
