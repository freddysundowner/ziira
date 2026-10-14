import { useState } from "react";

import { api, Button, Field, humanise, Input, NumberInput, Switch, toast, unwrap, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { atDefaults, type Check, draftChanges, paramKind, paramsToDraft, resetChanges } from "../logic";
import { SeverityBadge } from "./Badges";

/** One check: its words, an on/off switch, and its limits (numbers) with the defaults shown and a reset. */
export default function CheckCard({ check }: { check: Check }) {
  const { t } = useTranslation("intel");
  const qc = useQueryClient();
  const [draft, setDraft] = useState(() => paramsToDraft(check.params));
  const names = Object.keys(check.defaults);
  const changes = draftChanges(check, draft);
  const dirty = Object.keys(changes).length > 0;

  const update = useMutation({
    mutationFn: (body: { enabled?: boolean; params?: Record<string, unknown> }) => unwrap(api.PATCH("/api/v1/intel/checks/{code}", { params: { path: { code: check.code } }, body })),
    onSuccess: (saved, body) => {
      qc.setQueryData<Check[]>(["intel", "checks"], (all) => all?.map((c) => (c.code === saved.code ? saved : c)));
      setDraft(paramsToDraft(saved.params));
      toast(t(body.params ? "limitsSaved" : saved.enabled ? "checkOn" : "checkOff"), "ok");
    },
  });

  return (
    <div className="space-y-3 py-4 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium">{check.title}</p>
            <SeverityBadge severity={check.severity} />
          </div>
          <p className="mt-0.5 text-sm text-muted">{check.description}</p>
        </div>
        <Switch label={t("enableCheck", { title: check.title })} checked={check.enabled} disabled={update.isPending} onChange={(enabled) => update.mutate({ enabled })} />
      </div>
      {names.length > 0 && (
        <form className="space-y-3 rounded-lg bg-sunken/50 p-3" onSubmit={(e) => { e.preventDefault(); if (dirty) update.mutate({ params: changes }); }}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {names.map((name) => {
              const kind = paramKind(check.defaults[name]);
              const label = t(`param.${name}`, humanise(name));
              const hint = t("defaultIs", { value: String(check.defaults[name]) });
              return (
                <Field key={name} label={label} hint={hint}>
                  {kind === "boolean" ? <Switch label={label} checked={draft[name] === "true"} onChange={(v) => setDraft({ ...draft, [name]: String(v) })} />
                    : kind === "number" ? <NumberInput value={draft[name] ?? ""} onChange={(v) => setDraft({ ...draft, [name]: v })} />
                      : <Input value={draft[name] ?? ""} onChange={(e) => setDraft({ ...draft, [name]: e.target.value })} />}
                </Field>
              );
            })}
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            <Button type="button" size="sm" variant="ghost" disabled={atDefaults(check) || update.isPending} onClick={() => update.mutate({ params: resetChanges(check) })}>{t("resetLimits")}</Button>
            <Button type="submit" size="sm" disabled={!dirty} loading={update.isPending}>{t("saveLimits")}</Button>
          </div>
        </form>
      )}
    </div>
  );
}
