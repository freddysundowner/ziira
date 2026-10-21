import type { Edition, Schemas } from "@/sdk";

export type UnitCard = Schemas["UnitCard"];
export type UnitState = "unavailable" | "on" | "off";

/** Where a unit stands for this business: on, off (its data may be kept), or not offered by the platform yet. */
export function unitState(u: Pick<UnitCard, "installed" | "enabled">): UnitState {
  if (u.enabled) return "on";
  return u.installed ? "off" : "unavailable";
}

export type StatusFilter = "all" | "on" | "off";

const STATE_RANK: Record<UnitState, number> = { on: 0, off: 1, unavailable: 2 };

/** The cards to show in one flat list: matching the search words and status filter ("off" includes those not offered yet); switched on first, then available, then not available yet, alphabetical inside each. */
export function visibleCards(cards: readonly UnitCard[], query: string, status: StatusFilter): UnitCard[] {
  const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const matches = (c: UnitCard) => words.every((w) => `${c.title} ${c.name} ${c.description}`.toLowerCase().includes(w));
  return cards
    .filter((c) => matches(c) && (status === "all" || (status === "on") === (unitState(c) === "on")))
    .sort((x, y) => STATE_RANK[unitState(x)] - STATE_RANK[unitState(y)] || x.title.localeCompare(y.title));
}

/**
 * Plugins worth suggesting: not on yet, on offer, and either in a category the edition recommends and meant for this country (or for everywhere),
 * or a country pack that names this country (packs are suggested whatever the edition; the worldwide pack is applied at sign-up, not suggested).
 */
export function recommendedPlugins(cards: readonly UnitCard[], edition: Pick<Edition, "plugin_categories"> | undefined, country: string | null | undefined): UnitCard[] {
  const wanted = edition?.plugin_categories ?? [];
  const inCountry = (c: UnitCard) => !!country && c.countries.includes(country.toUpperCase());
  return cards.filter((c) => c.kind === "plugin" && !c.enabled && c.installed && !isIndustryPack(c)
    && (c.category === "country" ? inCountry(c) : wanted.includes(c.category) && (c.countries.length === 0 || inCountry(c))));
}

/** An industry pack: switched on from the same grid as the other add-ons, with an "Industry" badge. */
export const isIndustryPack = (c: Pick<UnitCard, "category">) => c.category === "industry";

/** An industry pack that names the business's edition among those it suits and is not on yet: "Recommended for your edition". */
export function recommendedForEdition(card: Pick<UnitCard, "category" | "editions" | "enabled">, editionId: string | undefined): boolean {
  return isIndustryPack(card) && !card.enabled && !!editionId && (card.editions ?? []).includes(editionId);
}

/** The country's name in the reader's language ("Kenya"), or the code when the browser does not know it. */
export function countryName(code: string | null | undefined, language: string): string {
  if (!code) return "";
  try {
    return new Intl.DisplayNames([language], { type: "region" }).of(code.toUpperCase()) ?? code;
  } catch {
    return code;
  }
}

/** Everything that switching to an edition would newly switch on, with what those units need (the server does the same). */
export function wouldSwitchOn(cards: readonly UnitCard[], edition: Pick<Edition, "units">): string[] {
  const byName = new Map(cards.map((c) => [c.name, c]));
  const out = new Set<string>();
  const visit = (name: string) => {
    const card = byName.get(name);
    if (!card || card.enabled || out.has(name)) return;
    out.add(name);
    card.requires.forEach(visit);
  };
  edition.units.forEach(visit);
  return [...out];
}

/** Human titles for unit names (a name the catalog does not know is shown as it is). */
export function titlesOf(cards: readonly UnitCard[], names: readonly string[]): string {
  const byName = new Map(cards.map((c) => [c.name, c.title]));
  return names.map((n) => byName.get(n) ?? n).join(", ");
}

/** Removing deletes data, so the unit's name must be typed exactly (surrounding spaces are forgiven). */
export function removeConfirmed(card: Pick<UnitCard, "name">, typed: string): boolean {
  return typed.trim() === card.name;
}

/**
 * How a unit that is not switched on is offered, in plain words: `buy` (the owner may pay once), `ask_owner` (for sale, but
 * this person may not pay), `bought` / `given` (it is theirs), `unavailable` (nothing to buy here) or `none` (in the plan).
 */
export type SaleView = "buy" | "ask_owner" | "bought" | "given" | "unavailable" | "none";

export function saleView(u: Pick<UnitCard, "sale_state" | "can_buy" | "bought_free" | "installed">): SaleView {
  if (!u.installed) return "none";
  switch (u.sale_state) {
    case "bought": return u.bought_free ? "given" : "bought";
    case "for_sale": return u.can_buy ? "buy" : "ask_owner";
    case "not_for_sale": return "unavailable";
    default: return "none";
  }
}
