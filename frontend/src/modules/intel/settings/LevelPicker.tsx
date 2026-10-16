import { useState } from "react";

import { Alert, ConfirmDialog, cx, useCan, useTranslation } from "@/sdk";

import { LEVELS, needsAutomationRight } from "../actions/logic";

interface Props {
  level: number;
  busy: boolean;
  error: string | null;
  onChange: (level: number) => void;
}

/** The four ways Ziira can work (Watch, Ask, Prepare, Act for me) as cards. Raising to 3 or 4 needs the Owner's automation right and asks for confirmation; so does lowering. */
export default function LevelPicker({ level, busy, error, onChange }: Props) {
  const { t } = useTranslation("intel");
  const mayRaise = useCan("intel.automation");
  const [asking, setAsking] = useState<number | null>(null);
  const blocked = (n: number) => needsAutomationRight(n) && n > level && !mayRaise;

  const message = (n: number) => {
    if (n > level) return t(`how.mode.${n}.raise`);
    return t(level >= 3 && n < 3 ? "how.lowerWithdraw" : level === 4 && n === 3 ? "how.lowerRules" : "how.lowerPlain", { name: t(`how.mode.${n}.name`) });
  };

  return (
    <fieldset className="space-y-3">
      <legend className="sr-only">{t("how.title")}</legend>
      <div className="grid gap-3 lg:grid-cols-2">
        {LEVELS.map((n) => {
          const disabled = busy || blocked(n);
          return (
            <label key={n} className={cx("flex gap-3 rounded-xl border p-4", n === level ? "border-brand bg-brand-soft" : "border-line bg-surface", disabled ? "cursor-not-allowed opacity-70" : "cursor-pointer hover:border-brand")}>
              <input type="radio" name="intel-level" className="mt-1 h-4 w-4 accent-brand" checked={n === level} disabled={disabled} onChange={() => setAsking(n)} />
              <span className="min-w-0 space-y-2 text-sm">
                <span className="block text-base font-semibold">{t(`how.mode.${n}.name`)}{n === level && <span className="ml-2 text-xs font-normal text-muted">{t("how.current")}</span>}</span>
                <span className="block">{t(`how.mode.${n}.does`)}</span>
                <span className="block text-muted"><span className="font-medium text-ink">{t("how.example")} </span>{t(`how.mode.${n}.example`)}</span>
                <span className="block text-muted"><span className="font-medium text-ink">{t("how.changes")} </span>{t(`how.mode.${n}.changes`)}</span>
                <span className="block text-muted"><span className="font-medium text-ink">{t("how.never")} </span>{t(`how.mode.${n}.never`)}</span>
                {blocked(n) && <span className="block text-xs text-warn">{t("how.ownerOnly")}</span>}
              </span>
            </label>
          );
        })}
      </div>
      <Alert tone="info">{t("how.neverMoves")}</Alert>
      {error && <Alert tone="bad">{error}</Alert>}
      <ConfirmDialog open={asking !== null} onClose={() => setAsking(null)} busy={busy} danger={asking !== null && asking < level}
        title={t("how.changeTitle", { name: asking === null ? "" : t(`how.mode.${asking}.name`) })} confirmLabel={t("how.changeConfirm")}
        message={asking === null ? "" : message(asking)} onConfirm={() => { if (asking !== null) onChange(asking); setAsking(null); }} />
    </fieldset>
  );
}
