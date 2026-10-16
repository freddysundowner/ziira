import { useState } from "react";

import { Alert, api, ApiError, Badge, Button, Card, ConfirmDialog, EDITION_KEY, toast, unwrap, useEdition, useEditionChoices, useMutation, useQueryClient, useTranslation } from "@/sdk";

import { titlesOf, wouldSwitchOn, type UnitCard } from "./lib";

/** The business's edition, a plain list of what is on, and the way to move to another edition (which only ever switches more on). */
export function EditionPanel({ cards, onChanged }: { cards: readonly UnitCard[]; onChanged: () => Promise<void> }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const { edition } = useEdition();
  const choices = useEditionChoices();
  const [target, setTarget] = useState<string>();
  const [open, setOpen] = useState(false);
  const chosen = choices.data?.find((e) => e.id === target);
  const others = (choices.data ?? []).filter((e) => e.id !== edition?.id);
  const on = cards.filter((c) => c.enabled);
  const switchEdition = useMutation({
    meta: { silent: true },
    mutationFn: (id: string) => unwrap(api.POST("/api/v1/edition", { body: { edition: id } })),
    onSuccess: async (r) => {
      qc.setQueryData(EDITION_KEY, r.mine);
      await onChanged();
      setTarget(undefined);
      toast(r.enabled.length ? t("apps.edition.switched", { names: titlesOf(cards, r.enabled) }) : t("apps.edition.switchedNothing"), "ok");
    },
  });
  if (!edition) return null;
  const adds = chosen ? wouldSwitchOn(cards, chosen) : [];
  const text = (id: string, field: "title" | "pitch", fallback: string) => t(`edition.${id}.${field}`, { ns: "shell", defaultValue: fallback });

  return (
    <Card className="mb-8" title={t("apps.edition.title")} description={text(edition.id, "title", edition.title)}
      actions={others.length > 0 && <Button size="sm" variant="secondary" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{t("apps.edition.change")}</Button>}>
      <div className="space-y-4">
        <p className="text-sm">{text(edition.id, "pitch", edition.pitch)}</p>
        <div>
          <h3 className="mb-1.5 text-sm font-semibold">{t("apps.edition.whatIsOn")}</h3>
          {on.length === 0 ? <p className="text-sm text-muted">{t("apps.edition.nothingOn")}</p> : (
            <ul className="flex flex-wrap gap-1.5" aria-label={t("apps.edition.whatIsOn")}>
              {on.map((u) => <li key={u.name}><Badge tone={u.kind === "module" ? "ok" : "neutral"}>{u.title}</Badge></li>)}
            </ul>
          )}
        </div>
        {open && (
          <div className="space-y-2 border-t border-line pt-3">
            <p className="text-sm text-muted">{t("apps.edition.changeHint")}</p>
            <div className="grid gap-2 sm:grid-cols-2">
              {others.map((e) => (
                <button key={e.id} type="button" onClick={() => { switchEdition.reset(); setTarget(e.id); }}
                  className="rounded-xl border border-line p-3 text-left text-sm hover:border-brand/50 hover:bg-sunken">
                  <span className="block font-medium">{text(e.id, "title", e.title)}</span>
                  <span className="text-muted">{text(e.id, "pitch", e.pitch)}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      {chosen && (
        <ConfirmDialog open onClose={() => setTarget(undefined)} busy={switchEdition.isPending} title={t("apps.edition.switchTitle", { name: text(chosen.id, "title", chosen.title) })}
          confirmLabel={t("apps.edition.switch")} onConfirm={() => switchEdition.mutate(chosen.id)}
          message={(
            <div className="space-y-3">
              <p>{adds.length > 0 ? t("apps.edition.willAdd", { names: titlesOf(cards, adds) }) : t("apps.edition.addsNothing")}</p>
              <p>{t("apps.edition.keeps")}</p>
              {switchEdition.error instanceof ApiError && <Alert tone="bad">{switchEdition.error.message}</Alert>}
            </div>
          )} />
      )}
    </Card>
  );
}
