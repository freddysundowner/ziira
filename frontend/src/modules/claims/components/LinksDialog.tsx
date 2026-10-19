import { Copy } from "lucide-react";
import { useState } from "react";

import { api, Alert, Badge, Button, Field, formatDate, Input, Modal, toast, unwrap, useQuery, useTranslation } from "@/sdk";

import { useClaimsMutation } from "../hooks";
import type { ClaimLink, Estimate } from "../types";

const tone = (s: string) => (s === "active" ? "ok" : s === "answered" ? "info" : "neutral") as "ok" | "info" | "neutral";

/** The response links of an estimate: make another, revoke one, and see every time a link was opened or answered. */
export function LinksDialog({ estimate, onClose }: { estimate: Estimate | null; onClose: () => void }) {
  const { t } = useTranslation("claims");
  const [fresh, setFresh] = useState("");
  const [watching, setWatching] = useState<ClaimLink | null>(null);
  const links = useQuery({
    queryKey: ["claims", "links", estimate?.id], enabled: estimate !== null,
    queryFn: () => unwrap(api.GET("/api/v1/claims/estimates/{estimate_id}/links", { params: { path: { estimate_id: estimate?.id ?? "" } } })),
  });
  const log = useQuery({
    queryKey: ["claims", "link-access", watching?.id], enabled: watching !== null,
    queryFn: () => unwrap(api.GET("/api/v1/claims/links/{link_id}/access", { params: { path: { link_id: watching?.id ?? "" } } })),
  });
  const make = useClaimsMutation(() => unwrap(api.POST("/api/v1/claims/estimates/{estimate_id}/links", { params: { path: { estimate_id: estimate?.id ?? "" } } })),
    { onDone: (r) => { setFresh(`${window.location.origin}${r.link_path}`); void links.refetch(); } });
  const revoke = useClaimsMutation((l: ClaimLink) => unwrap(api.DELETE("/api/v1/claims/links/{link_id}", { params: { path: { link_id: l.id } } })),
    { done: t("links.revoked"), onDone: () => void links.refetch() });
  const copy = async () => { try { await navigator.clipboard.writeText(fresh); toast(t("send.copied"), "ok"); } catch { toast(t("send.copyFailed"), "bad"); } };
  const close = () => { setFresh(""); setWatching(null); onClose(); };
  return (
    <Modal open={estimate !== null} onClose={close} title={t("links.title")} size="lg" footer={<Button onClick={close}>{t("common.done")}</Button>}>
      <div className="space-y-4">
        <p className="text-sm text-muted">{t("links.hint")}</p>
        {fresh && (
          <>
            <Alert tone="warn">{t("send.linkOnce")}</Alert>
            <Field label={t("send.link")}><div className="flex gap-2"><Input readOnly value={fresh} onFocus={(e) => e.currentTarget.select()} /><Button variant="secondary" onClick={() => void copy()}><Copy className="h-4 w-4" />{t("send.copy")}</Button></div></Field>
          </>
        )}
        <ul className="divide-y divide-line rounded-xl border border-line text-sm">
          {(links.data ?? []).map((l) => (
            <li key={l.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5">
              <span className="min-w-0">
                <span className="flex items-center gap-2"><Badge tone={tone(l.state)}>{t(`links.state.${l.state}`)}</Badge><span className="text-xs text-muted">{formatDate(l.created_at, true)}</span></span>
                <span className="block text-xs text-muted">
                  {t("links.expires", { date: formatDate(l.expires_at, true) })} · {t("links.views", { n: l.view_count })}
                  {l.sent_to ? ` · ${l.sent_to}` : ""}{l.signer_name ? ` · ${t("links.signedBy", { name: l.signer_name })}` : ""}
                </span>
              </span>
              <span className="flex gap-1">
                <Button size="sm" variant="ghost" onClick={() => setWatching(l)}>{t("links.access")}</Button>
                {l.state === "active" && <Button size="sm" variant="ghost" loading={revoke.isPending} onClick={() => revoke.mutate(l)}>{t("links.revoke")}</Button>}
              </span>
            </li>
          ))}
          {links.data?.length === 0 && <li className="px-3 py-4 text-center text-muted">{t("links.none")}</li>}
        </ul>
        {watching && (
          <div className="rounded-xl bg-sunken p-3 text-xs">
            <p className="mb-1 font-semibold">{t("links.accessTitle")}</p>
            <ul className="space-y-0.5">
              {(log.data ?? []).map((a, i) => <li key={i}>{formatDate(a.created_at, true)} · {t(`links.action.${a.action}`, { defaultValue: a.action })} · {a.outcome}{a.ip_address ? ` · ${a.ip_address}` : ""}</li>)}
              {log.data?.length === 0 && <li className="text-muted">{t("links.accessNone")}</li>}
            </ul>
          </div>
        )}
        {estimate?.status === "submitted" && <Button variant="secondary" loading={make.isPending} onClick={() => make.mutate(undefined)}>{t("links.make")}</Button>}
      </div>
    </Modal>
  );
}
