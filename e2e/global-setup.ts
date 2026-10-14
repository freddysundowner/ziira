import { mkdirSync, writeFileSync } from "node:fs";

import { Api, registerBusiness, unique } from "./lib/api";

/** One business shared by the journeys J2 to J10 (J1 registers its own through the form). */
export default async function globalSetup() {
  const tag = unique("shared");
  const owner = await registerBusiness(`Shared ${tag} Traders`, `owner@${tag}.test`, "e2e-pass-123");
  const api = await new Api(owner).signIn();
  // A second person with every right, for the journeys that need "someone else" (approvals, separation of duties)
  const roles = await api.get<{ id: string; name: string }[]>("/roles");
  const ownerRole = roles.find((r) => r.name === "Owner");
  const second = { email: `second@${tag}.test`, password: "e2e-pass-123", name: "Sam Second" };
  const user = await api.post("/users", { full_name: second.name, email: second.email, password: second.password });
  if (ownerRole) await api.post(`/users/${user.id}/roles`, { role_id: ownerRole.id, scope: "tenant" });
  mkdirSync(".state", { recursive: true });
  writeFileSync(".state/shared.json", JSON.stringify({ owner, second, business: owner.business }));
}
