import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

import { api, Button, Card, unwrap, useCan, useQuery, useTranslation } from "@/sdk";

import { checkinPath, cataloguePath } from "../public";

const LINKS: Record<string, string> = {
  plans: cataloguePath, services: cataloguePath, terms: `${cataloguePath}?tab=terms`, policies: `${cataloguePath}?tab=policies`, checkin: checkinPath,
};
const ORDER = ["plans", "services", "members", "checkin"];
const OPTIONAL = ["terms", "policies"];

/** The first-run checklist: only the steps still to do, each leading to the right page. Gone once everything is done. */
export function SetupCard({ companyId, onSignUp }: { companyId: string; onSignUp: () => void }) {
  const { t } = useTranslation("memberships");
  const canPlans = useCan("memberships.plans");
  const q = useQuery({
    enabled: !!companyId, retry: false, queryKey: ["memberships", "setup-steps", companyId],
    queryFn: () => unwrap(api.GET("/api/v1/memberships/setup-steps", { params: { query: { company_id: companyId } } })),
  });
  const hasPlan = q.data?.find((s) => s.id === "plans")?.done ?? false;
  const missingItem = hasPlan && q.data?.find((s) => s.id === "services")?.done === false;   // only a problem once a plan exists without an invoice item
  const steps = ORDER.filter((id) => id !== "services" || missingItem);
  const todo = steps.map((id) => q.data?.find((s) => s.id === id)).filter((s): s is NonNullable<typeof s> => !!s && !s.done);
  const optional = OPTIONAL.map((id) => q.data?.find((s) => s.id === id)).filter((s): s is NonNullable<typeof s> => !!s && !s.done);
  if (!q.data || todo.length === 0) return null;
  const required = q.data.filter((s) => steps.includes(s.id));
  const done = required.length - todo.length;
  return (
    <Card title={t("setup.title")} description={t("setup.progress", { done, total: required.length })} className="mb-4">
      <ul className="divide-y divide-line">
        {todo.map((s) => (
          <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
            <span><span className="font-medium">{t(`setup.steps.${s.id}.title`)}</span><span className="block text-sm text-muted">{t(`setup.steps.${s.id}.hint`)}</span></span>
            {s.id === "members"
              ? <Button variant="secondary" onClick={onSignUp}>{t("setup.go")}<ArrowRight className="h-4 w-4" /></Button>
              : (canPlans || s.id === "checkin") && LINKS[s.id]
                ? <Link to={LINKS[s.id] ?? ""} className="inline-flex h-10 items-center gap-2 rounded-lg border border-line bg-surface px-4 text-sm font-semibold shadow-card hover:bg-sunken">{t("setup.go")}<ArrowRight className="h-4 w-4" /></Link>
                : null}
          </li>
        ))}
      </ul>
      {optional.length > 0 && (
        <p className="mt-3 border-t border-line pt-3 text-sm text-muted">
          {t("setup.optional")}{" "}
          {optional.map((s, i) => (
            <span key={s.id}>{i > 0 && " · "}<Link className="font-medium text-brand-strong hover:underline" to={LINKS[s.id] ?? ""}>{t(`setup.steps.${s.id}.title`)}</Link></span>
          ))}
        </p>
      )}
    </Card>
  );
}
