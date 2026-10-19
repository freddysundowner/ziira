import { Gift, UserPlus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, Badge, Button, formatDate, money, type SlotProps, unwrap, useCan, useCurrency, useQuery, useTranslation } from "@/sdk";

import { MemberForm } from "../components/MemberForm";
import { SellPackageForm } from "../components/SellPackageForm";
import { credits, memberTone, packageTone } from "../logic";
import { memberPath } from "../public";

/** A tab on the customer page: this customer's memberships and packages, with what is left on each. */
export default function CustomerMembership(props: SlotProps) {
  const customerId = String(props.customerId);
  const companyId = String(props.companyId);
  const { t } = useTranslation("memberships");
  const canManage = useCan("memberships.manage");
  const currency = useCurrency(companyId);
  const [signing, setSigning] = useState(false);
  const [selling, setSelling] = useState(false);
  const q = useQuery({ queryKey: ["memberships", "customer", customerId], queryFn: () => unwrap(api.GET("/api/v1/memberships/customers/{customer_id}/credits", { params: { path: { customer_id: customerId } } })) });

  if (q.error) return <p className="text-sm text-bad">{q.error.message} <button type="button" className="underline" onClick={() => void q.refetch()}>{t("retry")}</button></p>;
  if (!q.data) return <p className="text-sm text-muted">{t("loading")}</p>;
  const { memberships, packages } = q.data;
  const nothing = memberships.length === 0 && packages.length === 0;

  return (
    <div className="space-y-4">
      {canManage && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setSigning(true)}><UserPlus className="h-4 w-4" />{t("signUp")}</Button>
          <Button size="sm" variant="secondary" onClick={() => setSelling(true)}><Gift className="h-4 w-4" />{t("sellPackage")}</Button>
        </div>
      )}
      {nothing && <p className="text-sm text-muted">{t("customerNothing")}</p>}
      {memberships.length > 0 && (
        <ul className="divide-y divide-line rounded-md border border-line text-sm">
          {memberships.map((m) => (
            <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <Link className="font-medium text-brand-strong hover:underline" to={memberPath(m.id)}>{m.plan_name}</Link>
              <span className="flex items-center gap-3 text-muted">
                <Badge tone={memberTone(m.status)}>{t(`memberStatus.${m.status}`, m.status)}</Badge>
                <span>{t("creditsNow", { count: Number(m.balance) })}</span>
                <span>{money(m.price, currency)} / {t(`intervalShort.${m.billing_interval}`)}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      {packages.length > 0 && (
        <ul className="divide-y divide-line rounded-md border border-line text-sm">
          {packages.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
              <span className="font-medium">{p.name}</span>
              <span className="flex items-center gap-3 text-muted">
                <Badge tone={packageTone(p.status)}>{t(`packageStatus.${p.status}`, p.status)}</Badge>
                <span>{t("ofTotal", { left: credits(p.balance), total: credits(p.credits) })}</span>
                <span>{p.expires_on ? t("expiresOn", { date: formatDate(p.expires_on) }) : t("neverExpires")}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      <MemberForm open={signing} onClose={() => setSigning(false)} customerId={customerId} />
      <SellPackageForm open={selling} onClose={() => setSelling(false)} customerId={customerId} />
    </div>
  );
}
