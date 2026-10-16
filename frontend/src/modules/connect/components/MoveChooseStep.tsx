import { Link } from "react-router-dom";

import { Alert, Button, Card, Checkbox, Field, FormGrid, Input, Select, useTranslation } from "@/sdk";
import type { Schemas } from "@/sdk";

import { MOVE_KINDS, type MoveKind, ready, SOURCE_OF } from "../moveLogic";

type Options = Schemas["MoveOptionsOut"];
type Choice = { unit: string; taxCode: string; asOf: string; locations: Record<string, string> };
interface Named { code: string; name: string }

/** Step one: tick what to bring over, say the go-live date, and the few things Ziira cannot guess. */
export function MoveChooseStep({ connectionId, options, chosen, onChosen, choice, onChoice, units, taxCodes, busy, onNext }: {
  connectionId: string; options: Options; chosen: MoveKind[]; onChosen: (k: MoveKind[]) => void; choice: Choice; onChoice: (c: Choice) => void;
  units: Named[] | undefined; taxCodes: Named[] | undefined; busy: boolean; onNext: () => void;
}) {
  const { t } = useTranslation("connect");
  const kinds = new Map(options.kinds.map((k) => [k.kind, k]));
  const toggle = (kind: MoveKind, on: boolean) => onChosen(MOVE_KINDS.filter((k) => (k === kind ? on : chosen.includes(k))));
  const stock = chosen.includes("opening_stock");
  const set = (patch: Partial<Choice>) => onChoice({ ...choice, ...patch });
  return (
    <div className="space-y-4">
      <Card title={t("move.choose.title")} description={t("move.choose.hint")}>
        <ul className="divide-y divide-line">
          {MOVE_KINDS.map((kind) => {
            const k = kinds.get(kind);
            if (!k) return null;
            const found = options.source_counts[SOURCE_OF[kind]] ?? 0;
            const usable = k.available && k.allowed;
            return (
              <li key={kind} className="flex flex-wrap items-start gap-3 py-3 first:pt-0 last:pb-0">
                <Checkbox aria-label={t(`move.kind.${kind}`)} label="" checked={chosen.includes(kind)} disabled={!usable} onChange={(e) => toggle(kind, e.target.checked)} />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{t(`move.kind.${kind}`)} <span className="tnum font-normal text-muted">· {found > 0 ? t("move.choose.found", { count: found }) : t("move.choose.nothing")}</span></p>
                  <p className="text-xs text-muted">{t(`move.kindHint.${kind}`)}</p>
                  {!k.available && (
                    <p className="mt-1 text-xs text-warn">
                      {t("move.choose.needsUnits", { units: k.needs.map((u) => t(`move.unit.${u}`, { defaultValue: u })).join(", ") })}{" "}
                      <Link to="/addons" className="font-medium underline">{t("move.choose.openApps")}</Link>
                    </p>
                  )}
                  {k.available && !k.allowed && <p className="mt-1 text-xs text-warn">{t("move.choose.notAllowed")}</p>}
                </div>
              </li>
            );
          })}
        </ul>
      </Card>

      <Card title={t("move.choose.details")}>
        <FormGrid>
          <Field label={t("move.choose.goLive")} hint={t("move.choose.goLiveHint")} required>
            <Input type="date" value={choice.asOf} onChange={(e) => set({ asOf: e.target.value })} />
          </Field>
          {chosen.includes("products") && (
            <>
              <Field label={t("move.choose.unit")} hint={t("move.choose.unitHint")} required>
                {units ? (
                  <Select value={choice.unit} onChange={(e) => set({ unit: e.target.value })}>
                    <option value="">{t("move.choose.pick")}</option>
                    {units.map((u) => <option key={u.code} value={u.code}>{u.name} ({u.code})</option>)}
                  </Select>
                ) : <Input value={choice.unit} onChange={(e) => set({ unit: e.target.value })} />}
              </Field>
              <Field label={t("move.choose.tax")} hint={t("move.choose.taxHint")} required>
                {taxCodes ? (
                  <Select value={choice.taxCode} onChange={(e) => set({ taxCode: e.target.value })}>
                    <option value="">{t("move.choose.pick")}</option>
                    {taxCodes.map((x) => <option key={x.code} value={x.code}>{x.name} ({x.code})</option>)}
                  </Select>
                ) : <Input value={choice.taxCode} onChange={(e) => set({ taxCode: e.target.value })} />}
              </Field>
            </>
          )}
        </FormGrid>
        {chosen.includes("products") && units?.length === 0 && <Alert tone="warn" className="mt-3">{t("move.choose.noUnits")} <Link to="/products-setup" className="font-medium underline">{t("move.choose.openSetup")}</Link></Alert>}
      </Card>

      {stock && (
        <Card title={t("move.choose.locations")} description={t("move.choose.locationsHint")}>
          <div className="space-y-3">
            {options.mapped_branches.map((b) => (
              <Field key={b.branch_id} label={b.branch_name ?? b.branch_id}>
                {b.locations.length === 0 ? <p className="text-sm text-bad">{t("move.choose.noLocation")}</p> : (
                  <Select value={choice.locations[b.branch_id] ?? b.locations[0].code} onChange={(e) => set({ locations: { ...choice.locations, [b.branch_id]: e.target.value } })}>
                    {b.locations.map((l) => <option key={l.code} value={l.code}>{l.name} ({l.code})</option>)}
                  </Select>
                )}
              </Field>
            ))}
            {options.mapped_branches.length === 0 && <p className="text-sm text-muted">{t("move.choose.noBranches")}</p>}
            {options.unmapped_branches > 0 && (
              <Alert tone="warn">{t("move.choose.unmapped", { count: options.unmapped_branches })}{" "}
                <Link to={`/connect/connections/${connectionId}`} className="font-medium underline">{t("move.choose.mapLink")}</Link></Alert>
            )}
          </div>
        </Card>
      )}

      <div className="flex justify-end">
        <Button loading={busy} disabled={!ready(chosen, choice.unit, choice.taxCode, choice.asOf)} onClick={onNext}>{t("move.choose.next")}</Button>
      </div>
    </div>
  );
}
