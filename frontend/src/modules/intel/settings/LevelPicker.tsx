import { useState } from "react";

import { Alert, ConfirmDialog, cx, useCan, useTranslation } from "@/sdk";

import { LEVELS, needsAutomationRight } from "../actions/logic";

interface Props {
  level: number;
  busy: boolean;
  error: string | null;
  onChange: (level: number) => void;
}

/** The four levels as cards. Raising to 3 or 4 needs the Owner's automation right and asks for confirmation; so does lowering. */
export default function LevelPicker({ level, busy, error, onChange }: Props) {
  const { t } = useTranslation("intel");
  const mayRaise = useCan("intel.automation");
  const [asking, setAsking] = useState<number | null>(null);
  const blocked = (n: number) => needsAutomationRight(n) && n > level && !mayRaise;

  const message = (n: number) => {
    if (n > level) return t(`settings.level.${n}.raise`);
    return t(level >= 3 && n < 3 ? "settings.lowerWithdraw" : level === 4 && n === 3 ? "settings.lowerRules" : "settings.lowerPlain", { level: n });
  };

  return (
    <fieldset className="space-y-3">
      <legend className="sr-only">{t("settings.levelTitle")}</legend>
      <div className="grid gap-3 lg:grid-cols-2">
        {LEVELS.map((n) => {
          const disabled = busy || blocked(n);
          return (
            <label key={n} className={cx("flex gap-3 rounded-xl border p-4", n === level ? "border-brand bg-brand-soft" : "border-line bg-surface", disabled ? "cursor-not-allowed opacity-70" : "cursor-pointer hover:border-brand")}>
              <input type="radio" name="intel-level" className="mt-1 h-4 w-4 accent-brand" checked={n === level} disabled={disabled} onChange={() => setAsking(n)} />
              <span className="min-w-0 space-y-1 text-sm">
                <span className="block font-semibold">{t("settings.levelName", { level: n, name: t(`settings.level.${n}.name`) })}{n === level && <span className="ml-2 text-xs font-normal text-muted">{t("settings.current")}</span>}</span>
                <span className="block">{t(`settings.level.${n}.does`)}</span>
                {blocked(n) && <span className="block text-xs text-muted">{t("settings.ownerOnly")}</span>}
              </span>
            </label>
          );
        })}
      </div>
      <Alert tone="info">{t("settings.never")}</Alert>
      {error && <Alert tone="bad">{error}</Alert>}
      <ConfirmDialog open={asking !== null} onClose={() => setAsking(null)} busy={busy} danger={asking !== null && asking < level}
        title={t("settings.changeTitle", { level: asking ?? level })} confirmLabel={t("settings.changeConfirm", { level: asking ?? level })}
        message={asking === null ? "" : message(asking)} onConfirm={() => { if (asking !== null) onChange(asking); setAsking(null); }} />
    </fieldset>
  );
}
