import { Badge, Button, Card, formatDate, money, toast, useTranslation } from "@/sdk";

import { openPrintable } from "../billing/InvoicesCard";
import { isIndustryPack, saleView, titlesOf, unitState, type UnitCard } from "./lib";

/** One module or plugin: what it does, where it stands, what it needs and what needs it, and the actions that apply. */
export function UnitCardView({ unit: u, all, recommended, forEdition, supportEmail, onEnable, onDisable, onRemove, onBuy }: {
  unit: UnitCard; all: readonly UnitCard[]; recommended?: boolean; forEdition?: boolean; supportEmail?: string; onEnable: () => void; onDisable: () => void; onRemove: () => void; onBuy?: () => void;
}) {
  const { t } = useTranslation("kernel");
  const state = unitState(u);
  const sale = saleView(u);
  const price = u.sale_price ? money(u.sale_price, (u.sale_currency ?? "").trim() || undefined) : "";
  const kindNote = isIndustryPack(u) ? <Badge tone="info">{t("apps.industry.badge")}</Badge> : u.kind === "plugin" ? <Badge tone="info">{t("apps.plugin")}</Badge> : null;
  const chip = state === "on" ? <Badge tone="ok">{t("apps.on")}</Badge>
    : state === "unavailable" ? <Badge tone="warn">{t("apps.unavailable")}</Badge>
    : <Badge>{t(u.has_data ? "apps.offKept" : "apps.off")}</Badge>;
  const owned = sale === "bought" || sale === "given";
  const canSwitchOn = state === "off" && u.in_plan;
  const receipt = () => { if (u.receipt_invoice_id) openPrintable(u.receipt_invoice_id).catch((e: unknown) => toast(e instanceof Error && e.message !== "blocked" ? e.message : t("billing.popupBlocked"), "bad")); };
  return (
    <Card className="flex h-full flex-col" title={u.title} description={t("apps.version", { version: u.version })} actions={<>{forEdition ? <Badge tone="ok">{t("apps.industry.recommendedEdition")}</Badge> : recommended && <Badge tone="info">{t("apps.recommended.badge")}</Badge>}{kindNote}{owned && <Badge tone="brand">{t(sale === "given" ? "apps.sale.given" : "apps.sale.bought")}</Badge>}{chip}</>}>
      <div className="flex h-full flex-col gap-3">
        {u.description && <p className="text-sm">{u.description}</p>}
        {u.requires.length > 0 && <p className="text-xs text-muted">{t("apps.needs", { names: titlesOf(all, u.requires) })}</p>}
        {u.dependants.length > 0 && <p className="text-xs text-muted">{t("apps.usedBy", { names: titlesOf(all, u.dependants) })}</p>}
        {state === "unavailable" && <p className="text-xs text-warn">{t("apps.unavailableHint")}</p>}
        {state === "on" && !u.can_disable && u.why_not_disable && <p className="text-xs text-muted">{u.why_not_disable}</p>}
        {state === "off" && u.has_data && !u.can_remove && u.why_not_remove && <p className="text-xs text-muted">{u.why_not_remove}</p>}
        {owned && u.bought_at && <p className="text-xs text-muted">{t(sale === "given" ? "apps.sale.givenOn" : "apps.sale.boughtOn", { date: formatDate(u.bought_at) })}</p>}
        {state !== "unavailable" && sale === "buy" && <p className="text-xs text-muted">{t("apps.sale.price", { price })}{u.sale_tax_inclusive ? ` ${t("apps.sale.taxIncl")}` : ""}</p>}
        {state !== "unavailable" && sale === "ask_owner" && <p className="text-xs text-muted">{t("apps.sale.askOwner", { price })}</p>}
        {state !== "unavailable" && sale === "unavailable" && (
          <p className="text-xs text-muted">
            <span className="font-medium">{t("apps.sale.unavailable")}.</span> {t("apps.sale.notIncluded")}
            {supportEmail && <>{" "}<a className="font-medium underline" href={`mailto:${supportEmail}?subject=${encodeURIComponent(u.title)}`}>{t("apps.sale.askUs")}</a></>}
          </p>
        )}
        <div className="mt-auto flex flex-wrap justify-end gap-2 pt-1">
          {u.can_remove && <Button size="sm" variant="ghost" className="text-bad" onClick={onRemove}>{t("apps.remove")}</Button>}
          {u.can_disable && <Button size="sm" variant="secondary" onClick={onDisable}>{t("apps.disable")}</Button>}
          {sale === "bought" && u.receipt_invoice_id && <Button size="sm" variant="ghost" onClick={receipt}>{t("apps.sale.receipt")}</Button>}
          {state === "off" && sale === "buy" && <Button size="sm" onClick={onBuy}>{t("apps.sale.buy", { price })}</Button>}
          {canSwitchOn && <Button size="sm" disabled={!u.can_enable} onClick={onEnable}>{t("apps.enable")}</Button>}
        </div>
      </div>
    </Card>
  );
}
