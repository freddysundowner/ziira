import { useState } from "react";

import { api, Button, Input, NumberInput, Switch, toast, unwrap, useCurrency, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { atDefaults, type Check, draftChanges, paramKind, paramsToDraft } from "../logic";
import { limitsOutsideSentence, type PlainCheck, splitSentence } from "../plainWords";

interface Props {
  check: Check;
  text: PlainCheck | undefined;
  labels: Record<string, string>;
  technical: boolean;
  companyId: string | undefined;
}

/**
 * One thing Ziira watches, as a plain sentence with its limits right in it ("Tell me when a customer is more than [30] days late"),
 * an on/off switch, the other limits under "More settings", and a way back to the recommended settings.
 */
export default function WatchRow({ check, text, labels, technical, companyId }: Props) {
  const { t } = useTranslation("intel");
  const qc = useQueryClient();
  const currency = useCurrency(companyId);
  const [draft, setDraft] = useState(() => paramsToDraft(check.params));
  const [more, setMore] = useState(false);
  const changes = draftChanges(check, draft);
  const dirty = Object.keys(changes).length > 0;
  const names = Object.keys(check.defaults);
  const rest = limitsOutsideSentence(text?.sentence, names);

  const saved = (next: Check, message: string) => {
    qc.setQueryData<Check[]>(["intel", "checks"], (all) => all?.map((c) => (c.code === next.code ? next : c)));
    void qc.invalidateQueries({ queryKey: ["intel", "topics"] });
    setDraft(paramsToDraft(next.params));
    toast(message, "ok");
  };
  const update = useMutation({
    mutationFn: (body: { enabled?: boolean; params?: Record<string, unknown> }) => unwrap(api.PATCH("/api/v1/intel/checks/{code}", { params: { path: { code: check.code } }, body })),
    onSuccess: (next, body) => saved(next, t(body.params ? "watch.saved" : next.enabled ? "watch.on" : "watch.off")),
  });
  const reset = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/intel/checks/{code}/reset", { params: { path: { code: check.code } } })),
    onSuccess: (next) => saved(next, t("watch.resetDone")),
  });

  const unit = text?.units ?? {};
  const label = (name: string) => labels[name] ?? name;
  const control = (name: string, inline: boolean) => {
    const kind = paramKind(check.defaults[name]);
    if (kind === "boolean") return <Switch label={label(name)} checked={draft[name] === "true"} onChange={(v) => setDraft({ ...draft, [name]: String(v) })} />;
    const input = kind === "number"
      ? <NumberInput aria-label={label(name)} className={inline ? "!h-8 w-24 !py-0" : undefined} value={draft[name] ?? ""} onChange={(v) => setDraft({ ...draft, [name]: v })} />
      : <Input aria-label={label(name)} className={inline ? "h-8 w-40" : undefined} value={draft[name] ?? ""} onChange={(e) => setDraft({ ...draft, [name]: e.target.value })} />;
    return (
      <span className="inline-flex items-center gap-1 align-middle">
        {unit[name] === "money" && currency && <span className="text-xs text-muted">{currency}</span>}
        {input}
        {unit[name] === "percent" && <span className="text-xs text-muted">%</span>}
      </span>
    );
  };

  const title = text?.title ?? check.title;
  return (
    <div className="space-y-2 py-4 first:pt-0 last:pb-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-medium">{title}</p>
          {technical && <p className="font-mono text-xs text-muted">{check.code} · {check.title}</p>}
          {text?.sentence ? (
            <p className="text-sm leading-8">
              {splitSentence(text.sentence).map((s, i) => s.kind === "text" ? <span key={i}>{s.text}</span> : <span key={i} className="mx-1">{control(s.name, true)}{technical && <span className="ml-1 font-mono text-xs text-muted">{s.name}</span>}</span>)}
            </p>
          ) : text?.why ? <p className="text-sm text-muted">{text.why}</p> : <p className="text-sm text-muted">{check.description}</p>}
        </div>
        <Switch label={t("watch.switch", { title })} checked={check.enabled} disabled={update.isPending} onChange={(enabled) => update.mutate({ enabled })} />
      </div>
      {rest.length > 0 && (
        <div>
          <button type="button" aria-expanded={more} onClick={() => setMore(!more)} className="text-xs font-medium text-brand-strong hover:underline">{more ? t("watch.lessSettings") : t("watch.moreSettings")}</button>
          {more && (
            <div className="mt-2 grid gap-3 rounded-lg bg-sunken/50 p-3 sm:grid-cols-2">
              {rest.map((name) => (
                <div key={name} className="space-y-1">
                  <p className="text-sm">{label(name)}</p>
                  {technical && <p className="font-mono text-xs text-muted">{name}</p>}
                  {control(name, false)}
                  <p className="text-xs text-muted">{t("watch.recommendedIs", { value: String(check.defaults[name]) })}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {(dirty || !atDefaults(check) || !check.enabled) && (
        <div className="flex flex-wrap justify-end gap-2">
          <Button size="sm" variant="ghost" loading={reset.isPending} onClick={() => reset.mutate()}>{t("watch.reset")}</Button>
          {dirty && <Button size="sm" loading={update.isPending} onClick={() => update.mutate({ params: changes })}>{t("watch.save")}</Button>}
        </div>
      )}
    </div>
  );
}
