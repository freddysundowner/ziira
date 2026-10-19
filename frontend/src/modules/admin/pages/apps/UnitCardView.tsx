import { Link } from "react-router-dom";

import { Badge, Button, Card, useTranslation } from "@/sdk";

import { isIndustryPack, titlesOf, unitState, type UnitCard } from "./lib";

/** One module or plugin: what it does, where it stands, what it needs and what needs it, and the actions that apply. */
export function UnitCardView({ unit: u, all, recommended, forEdition, onEnable, onDisable, onRemove }: {
  unit: UnitCard; all: readonly UnitCard[]; recommended?: boolean; forEdition?: boolean; onEnable: () => void; onDisable: () => void; onRemove: () => void;
}) {
  const { t } = useTranslation("kernel");
  const state = unitState(u);
  const kindNote = isIndustryPack(u) ? <Badge tone="info">{t("apps.industry.badge")}</Badge> : u.kind === "plugin" ? <Badge tone="info">{t("apps.plugin")}</Badge> : null;
  const chip = state === "on" ? <Badge tone="ok">{t("apps.on")}</Badge>
    : state === "unavailable" ? <Badge tone="warn">{t("apps.unavailable")}</Badge>
    : <Badge>{t(u.has_data ? "apps.offKept" : "apps.off")}</Badge>;
  return (
    <Card className="flex h-full flex-col" title={u.title} description={t("apps.version", { version: u.version })} actions={<>{forEdition ? <Badge tone="ok">{t("apps.industry.recommendedEdition")}</Badge> : recommended && <Badge tone="info">{t("apps.recommended.badge")}</Badge>}{kindNote}{chip}</>}>
      <div className="flex h-full flex-col gap-3">
        {u.description && <p className="text-sm">{u.description}</p>}
        {u.requires.length > 0 && <p className="text-xs text-muted">{t("apps.needs", { names: titlesOf(all, u.requires) })}</p>}
        {u.dependants.length > 0 && <p className="text-xs text-muted">{t("apps.usedBy", { names: titlesOf(all, u.dependants) })}</p>}
        {state === "unavailable" && <p className="text-xs text-warn">{t("apps.unavailableHint")}</p>}
        {state === "on" && !u.can_disable && u.why_not_disable && <p className="text-xs text-muted">{u.why_not_disable}</p>}
        {state === "off" && u.has_data && !u.can_remove && u.why_not_remove && <p className="text-xs text-muted">{u.why_not_remove}</p>}
        {state === "off" && !u.in_plan && (
          <p className="text-xs text-warn">
            <span className="font-medium">{t("billing.appsNotInPlan")}</span>{u.why_not_enable ? ` ${u.why_not_enable}` : ""}{" "}
            <Link to="/admin/billing" className="font-medium underline">{t("billing.appsUpgrade")}</Link>
          </p>
        )}
        <div className="mt-auto flex flex-wrap justify-end gap-2 pt-1">
          {u.can_remove && <Button size="sm" variant="ghost" className="text-bad" onClick={onRemove}>{t("apps.remove")}</Button>}
          {u.can_disable && <Button size="sm" variant="secondary" onClick={onDisable}>{t("apps.disable")}</Button>}
          {state === "off" && <Button size="sm" disabled={!u.can_enable || !u.in_plan} onClick={onEnable}>{t("apps.enable")}</Button>}
        </div>
      </div>
    </Card>
  );
}
