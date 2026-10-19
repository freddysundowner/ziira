import { useState } from "react";

import { api, Badge, Button, Card, formatDate, Skeleton, unwrap, useCan, useQuery, useTranslation } from "@/sdk";

import { TermsDialog } from "./TermsDialog";

/** Whether the person has accepted the current terms, who recorded it and when. */
export function TermsCard({ customerId, companyId, personName }: { customerId: string; companyId: string; personName?: string | null }) {
  const { t } = useTranslation("memberships");
  const canManage = useCan("memberships.manage");
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ["memberships", "waiver", customerId], queryFn: () => unwrap(api.GET("/api/v1/memberships/customers/{customer_id}/waiver", { params: { path: { customer_id: customerId } } })) });
  const s = q.data;
  return (
    <Card title={t("waiver.title")} actions={canManage && s?.current_version != null && !s.accepted_current && <Button onClick={() => setOpen(true)}>{t("waiver.record")}</Button>}>
      {q.error ? <p className="text-sm text-bad">{q.error.message} <button type="button" className="underline" onClick={() => void q.refetch()}>{t("retry")}</button></p>
        : !s ? <Skeleton className="h-20 w-full" />
        : s.current_version === null ? <p className="text-sm text-muted">{t("waiver.noneYet")}</p>
        : (
          <div className="space-y-3">
            <p className="flex items-center gap-2 text-sm"><Badge tone={s.accepted_current ? "ok" : "warn"}>{s.accepted_current ? t("waiver.acceptedBadge") : t("waiver.notAccepted")}</Badge>{s.current_title} · {t("waiver.version", { version: s.current_version })}</p>
            {s.acceptances.length > 0 && (
              <ul className="divide-y divide-line text-sm">
                {s.acceptances.map((a) => (
                  <li key={a.id} className="flex flex-wrap justify-between gap-2 py-2">
                    <span>{t("waiver.acceptedBy", { name: a.accepted_name, version: a.version })}</span>
                    <span className="text-muted">{formatDate(a.accepted_at, true)} · {t(`waiver.methods.${a.method}`, a.method)}{a.recorded_by_name ? ` · ${a.recorded_by_name}` : ""}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>)}
      <TermsDialog open={open} onClose={() => setOpen(false)} customerId={customerId} companyId={companyId} personName={personName} />
    </Card>
  );
}
