import { FilePlus2, KeyRound, Mail, Tag, UserPlus } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";

import { Button, useTranslation } from "@/sdk";

import { useOperatorMe } from "../../me";

const ACTIONS: { id: string; to: string; icon: LucideIcon; needs: string }[] = [
  { id: "plan", to: "/operator/plans/new", icon: Tag, needs: "platform.plans" },
  { id: "invoice", to: "/operator/billing/invoices?new=1", icon: FilePlus2, needs: "platform.billing" },
  { id: "licence", to: "/operator/licences?new=1", icon: KeyRound, needs: "platform.licences" },
  { id: "operator", to: "/operator/operators?new=1", icon: UserPlus, needs: "platform.operators" },
  { id: "email", to: "/operator/email", icon: Mail, needs: "platform.settings" },
];

/** The five things an owner does most, as buttons; a role sees only those it may do. */
export function QuickActions() {
  const { t } = useTranslation("operator");
  const permissions = useOperatorMe().data?.permissions ?? [];
  const mine = ACTIONS.filter((a) => permissions.includes(a.needs));
  if (mine.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t("dash.quick.title")}>
      {mine.map((a, i) => (
        <Link key={a.id} to={a.to}>
          <Button variant={i === 0 ? "primary" : "secondary"} size="sm"><a.icon className="h-4 w-4" aria-hidden /> {t(`dash.quick.${a.id}`)}</Button>
        </Link>
      ))}
    </div>
  );
}
