import type { Schemas } from "@/sdk";

export type UnitCard = Schemas["UnitCard"];
export type UnitState = "unavailable" | "on" | "off";

/** Where a unit stands for this business: on, off (its data may be kept), or not offered by the platform yet. */
export function unitState(u: Pick<UnitCard, "installed" | "enabled">): UnitState {
  if (u.enabled) return "on";
  return u.installed ? "off" : "unavailable";
}

/** Modules first, then plugins, each in the order the server sent them. */
export function splitByKind(cards: readonly UnitCard[]): { modules: UnitCard[]; plugins: UnitCard[] } {
  return { modules: cards.filter((c) => c.kind === "module"), plugins: cards.filter((c) => c.kind !== "module") };
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
