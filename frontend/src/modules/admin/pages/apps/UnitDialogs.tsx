import { type ReactNode, useState } from "react";

import { Alert, ApiError, Button, ConfirmDialog, Field, Input, Modal, useTranslation } from "@/sdk";

import { removeConfirmed, titlesOf, type UnitCard } from "./lib";

export interface Pending {
  kind: "enable" | "disable" | "remove";
  unit: UnitCard;
}
/** The part of a mutation these dialogs use. */
export interface UnitMutation {
  mutate: (unit: UnitCard) => void;
  isPending: boolean;
  error: Error | null;
}

/** The confirmation for each action: what else is switched on, what disappears, or the typed name before data is deleted. */
export function UnitDialogs({ pending, all, mutations, onClose }: {
  pending: Pending | undefined; all: readonly UnitCard[]; mutations: Record<Pending["kind"], UnitMutation>; onClose: () => void;
}) {
  const { t } = useTranslation("kernel");
  if (!pending) return null;
  const { kind, unit } = pending;
  const m = mutations[kind];
  const failure = m.error instanceof ApiError ? <Alert tone="bad">{m.error.message}</Alert> : null;
  const go = () => m.mutate(unit);
  if (kind === "remove") return <RemoveDialog unit={unit} busy={m.isPending} failure={failure} onClose={onClose} onConfirm={go} />;
  return kind === "enable" ? (
    <ConfirmDialog open onClose={onClose} busy={m.isPending} title={t("apps.enableTitle", { name: unit.title })} confirmLabel={t("apps.enable")} onConfirm={go}
      message={<div className="space-y-3"><p>{t("apps.enableAsk", { name: unit.title })}</p>
        {unit.will_also_enable.length > 0 && <p>{t("apps.enableAlso", { name: unit.title, names: titlesOf(all, unit.will_also_enable) })}</p>}{failure}</div>} />
  ) : (
    <ConfirmDialog open onClose={onClose} busy={m.isPending} title={t("apps.disableTitle", { name: unit.title })} confirmLabel={t("apps.disable")} onConfirm={go}
      message={<div className="space-y-3"><p>{t("apps.disableAsk")}</p>{failure}</div>} />
  );
}

function RemoveDialog({ unit, busy, failure, onClose, onConfirm }: { unit: UnitCard; busy: boolean; failure: ReactNode; onClose: () => void; onConfirm: () => void }) {
  const { t } = useTranslation("kernel");
  const [typed, setTyped] = useState("");
  return (
    <Modal open onClose={onClose} title={t("apps.removeTitle", { name: unit.title })} size="sm"
      footer={<><Button variant="secondary" onClick={onClose}>{t("apps.cancel")}</Button><Button variant="danger" loading={busy} disabled={!removeConfirmed(unit, typed)} onClick={onConfirm}>{t("apps.remove")}</Button></>}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (removeConfirmed(unit, typed)) onConfirm(); }}>
        <Alert tone="bad">{t("apps.removeAsk", { name: unit.title })}</Alert>
        <Field label={t("apps.removeType", { name: unit.name })}>
          <Input value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" spellCheck={false} data-autofocus />
        </Field>
        {failure}
      </form>
    </Modal>
  );
}
