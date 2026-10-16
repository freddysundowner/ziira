import { Alert, money, useTranslation } from "@/sdk";

import { owedEntries, type MyPlan } from "./lib";

/** What the owner must know first: a warning or blocked state, in the API's words, with what is owed. */
export function StateBanner({ plan }: { plan: MyPlan }) {
  const { t } = useTranslation("kernel");
  if (plan.access === "full" && plan.status !== "trialing") return null;
  const tone = plan.access === "full" ? "info" : plan.access === "warning" ? "warn" : "bad";
  const owed = owedEntries(plan.owed);
  return (
    <Alert tone={tone} className="mb-4">
      {plan.message && <p className="font-medium">{plan.message}</p>}
      {owed.length > 0 && <p>{t("billing.owed", { amount: owed.map(([c, v]) => money(v, c)).join(" · ") })}</p>}
    </Alert>
  );
}
