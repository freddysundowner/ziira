/** Group permission codes by the unit that owns them, for the API key scope picker. */
export interface ScopePermission {
  code: string;
  unit_name: string;
  description: string;
}

export function groupByUnit(permissions: readonly ScopePermission[]): { unit: string; permissions: ScopePermission[] }[] {
  const groups = new Map<string, ScopePermission[]>();
  for (const p of permissions) groups.set(p.unit_name, [...(groups.get(p.unit_name) ?? []), p]);
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([unit, list]) => ({ unit, permissions: list }));
}

/** Toggle one scope, or all of a group's scopes at once. */
export function toggleScopes(selected: readonly string[], codes: readonly string[], on: boolean): string[] {
  const rest = selected.filter((c) => !codes.includes(c));
  return on ? [...rest, ...codes] : rest;
}
