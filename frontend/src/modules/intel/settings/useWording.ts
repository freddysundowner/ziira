import { money, useCompany, useTranslation } from "@/sdk";

import type { Wording } from "../actions/schema";

/** How a rule's conditions are put into words for one company: its branch names and its currency for amounts. */
export function useWording(companyId: string | undefined): Wording {
  const { t } = useTranslation("intel");
  const { company } = useCompany(companyId);
  return {
    yes: t("yes"),
    no: t("no"),
    branchName: (id) => company?.branches.find((b) => b.id === id)?.name,
    special: (field, value) => (field.type === "number" && field.name.includes("amount") ? money(String(value), company?.currency) : undefined),
  };
}
