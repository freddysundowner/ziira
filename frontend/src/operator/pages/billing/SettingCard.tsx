import { type ReactNode, useState } from "react";

import { Alert, Button, Card, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";
import { useRefreshOperator } from "./invoiceDialogs";

/**
 * One platform setting with its own Save: the server validates that one value and its message is shown right here.
 * The card starts again from the stored value whenever that changes (its `key` carries it).
 */
export function SettingCard<D>({ settingKey, title, hint, stored, toDraft, fromDraft, editable, children, className }: {
  settingKey: string;
  title: string;
  hint?: string;
  stored: unknown;
  toDraft: (stored: unknown) => D;
  fromDraft: (draft: D) => unknown;
  editable: boolean;
  children: (draft: D, set: (next: D) => void) => ReactNode;
  className?: string;
}) {
  const { t } = useTranslation("operator");
  const refresh = useRefreshOperator();
  const initial = toDraft(stored);
  const [draft, setDraft] = useState<D>(initial);
  const [problem, setProblem] = useState<string | null>(null);
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);

  const save = useChange(
    () => opUnwrap(opApi.PUT("/api/v1/operator/platform-settings/{key}", { params: { path: { key: settingKey } }, body: { value: fromDraft(draft) } })),
    {
      onSuccess: () => { toast(t("billing.settings.saved", { name: title }), "ok"); refresh(); },
      onError: (error) => setProblem(error.message),
    },
  );
  return (
    <Card title={title} description={hint} className={className}>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (dirty && editable && !save.isPending) { setProblem(null); save.mutate(undefined); } }}>
        <fieldset disabled={!editable} className="space-y-3">{children(draft, (next) => { setDraft(next); setProblem(null); })}</fieldset>
        {problem && <Alert tone="bad">{problem}</Alert>}
        {editable && (
          <div className="flex justify-end gap-2">
            {dirty && <Button variant="ghost" size="sm" onClick={() => { setDraft(initial); setProblem(null); }}>{t("billing.settings.undo")}</Button>}
            <Button type="submit" size="sm" loading={save.isPending} disabled={!dirty}>{t("billing.settings.save")}</Button>
          </div>
        )}
      </form>
    </Card>
  );
}
