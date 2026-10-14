import type { Schemas } from "@/sdk";

export interface BranchInfo {
  id: string;
  name: string;
  code: string;
  companyId: string;
  currency: string;
}

/** Every branch the user can reach, with the company currency its sales are in. */
export function branchesOf(companies: Schemas["CompanyOut"][]): BranchInfo[] {
  return companies.flatMap((c) => c.branches.map((b) => ({ id: b.id, name: b.name, code: b.code, companyId: c.id, currency: c.currency })));
}
