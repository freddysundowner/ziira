import { Copy, Printer } from "lucide-react";
import { useEffect, useState } from "react";

import { api, Alert, Button, Field, Input, Modal, Select, toast, unwrap, useChannels, useTranslation } from "@/sdk";

import { openPrintable, useClaimsMutation } from "../hooks";
import type { Claim, Estimate, Payer } from "../types";

/** How the payer gets the estimate: a message on any channel the business has (the link goes in it), the secure link to pass on yourself, or by hand. */
export function SendDialog({ estimate, claim, payer, onClose }: { estimate: Estimate | null; claim: Claim; payer: Payer | undefined; onClose: () => void }) {
  const { t } = useTranslation("claims");
  const channels = useChannels(claim.company_id);
  const ready = (channels.data ?? []).filter((c) => c.configured);
  const [how, setHow] = useState("link");
  const [to, setTo] = useState("");
  const [sent, setSent] = useState<{ link: string; queued: boolean } | null>(null);
  const isEmail = how === "email";
  useEffect(() => {
    if (!estimate) return;
    setSent(null); setHow("link");
  }, [estimate]);
  useEffect(() => {
    if (how === "link" || how === "hand") { setTo(""); return; }
    const contact = payer?.contacts.find((c) => (isEmail ? c.email : c.phone));
    setTo(isEmail ? payer?.estimate_email ?? String(contact?.email ?? "") : String(contact?.phone ?? ""));
  }, [how, isEmail, payer]);
  const send = useClaimsMutation(
    (e: Estimate) => unwrap(api.POST("/api/v1/claims/estimates/{estimate_id}/submit", { params: { path: { estimate_id: e.id } }, body: {
      channel: how === "link" || how === "hand" ? null : how, recipient: how === "link" || how === "hand" ? null : to.trim() || null, make_link: how !== "hand" } })),
    { silent: true, onDone: (r) => setSent({ link: r.link_path ? `${window.location.origin}${r.link_path}` : "", queued: r.queued }) });
  const copy = async (link: string) => { try { await navigator.clipboard.writeText(link); toast(t("send.copied"), "ok"); } catch { toast(t("send.copyFailed"), "bad"); } };
  const channelLabel = (c: string) => ready.find((r) => r.channel === c)?.label ?? c;
  return (
    <Modal open={estimate !== null} onClose={onClose} title={sent ? t("send.sentTitle") : t("send.title", { label: estimate?.label ?? "" })} size="sm"
      footer={sent ? <Button onClick={onClose}>{t("common.done")}</Button> : <><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button loading={send.isPending} onClick={() => estimate && send.mutate(estimate)}>{t("send.send")}</Button></>}>
      {sent ? (
        <div className="space-y-4">
          {sent.queued && <Alert tone="ok">{t("send.queued", { channel: channelLabel(how) })}</Alert>}
          {!sent.queued && how !== "link" && how !== "hand" && <Alert tone="warn">{t("send.notQueued")}</Alert>}
          {sent.link ? (
            <>
              <Alert tone="warn">{t("send.linkOnce")}</Alert>
              <Field label={t("send.link")}>
                <div className="flex gap-2"><Input readOnly value={sent.link} onFocus={(e) => e.currentTarget.select()} /><Button variant="secondary" onClick={() => void copy(sent.link)}><Copy className="h-4 w-4" />{t("send.copy")}</Button></div>
              </Field>
            </>
          ) : <p className="text-sm text-muted">{t("send.byHandDone")}</p>}
          {estimate && <Button variant="secondary" onClick={() => void openPrintable(estimate.id).catch(() => toast(t("send.printFailed"), "bad"))}><Printer className="h-4 w-4" />{t("estimate.print")}</Button>}
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-muted">{t("send.hint")}</p>
          {send.error && <Alert tone="bad">{send.error.message}</Alert>}
          <Field label={t("send.how")}>
            <Select value={how} onChange={(e) => setHow(e.target.value)}>
              <option value="link">{t("send.optLink")}</option>
              {ready.map((c) => <option key={c.channel} value={c.channel}>{t("send.optChannel", { channel: c.label })}</option>)}
              <option value="hand">{t("send.optHand")}</option>
            </Select>
          </Field>
          {how !== "link" && how !== "hand" && (
            <Field label={isEmail ? t("send.toEmail") : t("send.toPhone")} hint={t("send.toHint")}>
              <Input value={to} maxLength={200} type={isEmail ? "email" : "tel"} onChange={(e) => setTo(e.target.value)} />
            </Field>
          )}
          {how === "hand" && <p className="text-sm text-muted">{t("send.handHint")}</p>}
          {claim.required_documents.length > 0 && <Alert tone="info">{t("send.documents", { list: claim.required_documents.join(", ") })}</Alert>}
        </div>
      )}
    </Modal>
  );
}
