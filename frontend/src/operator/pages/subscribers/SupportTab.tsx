import { useState } from "react";

import { Alert, Button, Card, ErrorState, formatDate, Modal, type Schemas, Skeleton, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useOperatorCan } from "../../me";
import { useChange } from "../../stepUp";
import { useRefreshOperator } from "../billing/invoiceDialogs";
import { useBusiness } from "./useBusiness";

/** Support access: the business's own grant (the console never bypasses it), and the support sessions that are open. */
export function SupportTab({ code }: { code: string }) {
  const { t } = useTranslation("operator");
  const canOpen = useOperatorCan("platform.subscribers");
  const refresh = useRefreshOperator();
  const business = useBusiness(code);
  const [opened, setOpened] = useState<Schemas["SupportSessionOut"] | null>(null);

  const open = useChange(
    () => opUnwrap(opApi.POST("/api/v1/operator/businesses/{code}/support-session", { params: { path: { code } } })),
    { onSuccess: (session) => { setOpened(session); refresh(); } },
  );
  const end = useChange(
    (id: string) => opUnwrap(opApi.POST("/api/v1/operator/sessions/{session_id}/end", { params: { path: { session_id: id } } })).then(() => undefined),
    { onSuccess: () => { toast(t("business.ended"), "ok"); refresh(); } },
  );

  if (business.isPending) return <Skeleton className="h-40 w-full" />;
  if (business.isError) return <ErrorState title={t("business.loadFailed")} message={business.error.message} onRetry={() => void business.refetch()} />;
  const b = business.data;
  const grant = b.grants[0];

  return (
    <>
      <Card title={t("business.support")} description={t("business.supportHint")}>
        {b.status !== "active" ? (
          <p className="text-sm text-muted">{t("business.notActive")}</p>
        ) : grant ? (
          <div className="space-y-3">
            <Alert tone="ok">{t("business.grantActive", { level: t(`business.levels.${grant.level}`), until: formatDate(grant.expires_at, true) })}<br /><span className="text-xs">{t("business.grantReason", { reason: grant.reason })}</span></Alert>
            {canOpen && <Button loading={open.isPending} onClick={() => open.mutate(undefined)}>{t("business.openSession")}</Button>}
          </div>
        ) : (
          <Alert tone="info">{t("business.noGrant")}</Alert>
        )}
        {b.sessions.length > 0 && (
          <ul className="mt-4 divide-y divide-line rounded-lg border border-line">
            {b.sessions.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                <span>{s.operator_name} <span className="text-xs text-muted">· {t(`business.levels.${s.level}`)} · {t("business.until", { time: formatDate(s.expires_at, true) })}</span></span>
                {s.mine
                  ? <Button size="sm" variant="secondary" loading={end.isPending && end.variables === s.id} onClick={() => end.mutate(s.id)}>{t("business.end")}</Button>
                  : <span className="text-xs text-muted">{t("business.otherStaff")}</span>}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {opened && <SessionOpened session={opened} onClose={() => setOpened(null)} />}
    </>
  );
}

function SessionOpened({ session, onClose }: { session: Schemas["SupportSessionOut"]; onClose: () => void }) {
  const { t } = useTranslation("operator");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(session.access_token);
      toast(t("business.copied"), "ok");
    } catch {
      toast(t("business.copyFailed"), "bad");
    }
  };
  return (
    <Modal open onClose={onClose} title={t("business.sessionOpened")} size="sm" footer={<><Button variant="secondary" onClick={() => void copy()}>{t("business.copyToken")}</Button><Button onClick={onClose}>{t("done")}</Button></>}>
      <div className="space-y-3 text-sm">
        <p>{t("business.sessionDetails", { business: session.business, level: t(`business.levels.${session.level}`), until: formatDate(session.expires_at, true) })}</p>
        <Alert tone="warn">{t("business.tokenWarning")}</Alert>
      </div>
    </Modal>
  );
}
