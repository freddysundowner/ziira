import { useState } from "react";

import {
  api, Alert, Badge, Button, ConfirmDialog, DetailList, Drawer, Field, formatDate, Input, Modal, money, NumberInput, toast, unwrap, useCan, useCurrency, useMutation,
  useQueryClient, useTranslation,
} from "@/sdk";

import type { SoldPackage } from "../hooks";
import { credits, packageTone } from "../logic";
import { LedgerTable } from "./LedgerTable";
import { RunsTable } from "./RunsTable";

/** One package a customer bought: what is left, when it expires, every change of its credits, and refund or adjust. */
export function PackageDrawer({ item, onClose }: { item: SoldPackage | null; onClose: () => void }) {
  const { t } = useTranslation("memberships");
  const qc = useQueryClient();
  const currency = useCurrency(item?.company_id);
  const canAdjust = useCan("memberships.credits");
  const [refunding, setRefunding] = useState(false);
  const [adjusting, setAdjusting] = useState(false);
  const [note, setNote] = useState("");
  const [amount, setAmount] = useState("");
  const live = item?.status === "active";
  const done = (message: string) => { void qc.invalidateQueries({ queryKey: ["memberships"] }); toast(message, "ok"); };

  const refund = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/sold-packages/{sold_id}/refund", { params: { path: { sold_id: item?.id ?? "" } }, body: { note: note.trim() } })),
    onSuccess: () => { done(t("refundedDone")); setRefunding(false); onClose(); },
  });
  const adjust = useMutation({
    meta: { silent: true }, onError: (e) => toast((e as Error).message, "bad"),
    mutationFn: () => unwrap(api.POST("/api/v1/memberships/credits/adjust", { body: { holder_type: "package", holder_id: item?.id ?? "", quantity: amount, note: note.trim() } })),
    onSuccess: () => { done(t("adjusted")); setAdjusting(false); onClose(); },
  });

  return (
    <Drawer open={!!item} onClose={onClose} title={item ? `${item.number} · ${item.name}` : ""}
      footer={item && live && canAdjust ? (
        <><Button variant="secondary" onClick={() => { setNote(""); setAmount(""); setAdjusting(true); }}>{t("adjustCredits")}</Button>
          <Button variant="danger" onClick={() => { setNote(""); setRefunding(true); }}>{t("refund")}</Button></>) : undefined}>
      {item && (
        <div className="space-y-5">
          <DetailList items={[
            { label: t("customer"), value: item.customer_name ?? "—" },
            { label: t("status"), value: <Badge tone={packageTone(item.status)}>{t(`packageStatus.${item.status}`, item.status)}</Badge> },
            { label: t("creditsLeft"), value: <span className="font-semibold">{t("ofTotal", { left: credits(item.balance), total: credits(item.credits) })}</span> },
            { label: t("soldOn"), value: formatDate(item.purchased_on) },
            { label: t("expires"), value: item.expires_on ? formatDate(item.expires_on) : t("neverExpires") },
            { label: t("price"), value: money(item.price, currency) },
            { label: t("covers"), value: item.covered_services.length ? item.covered_services.join(", ") : t("allServices") },
          ]} />
          {item.notes && <Alert tone="info">{item.notes}</Alert>}
          <div><h3 className="mb-2 text-sm font-semibold">{t("creditsLedger")}</h3><LedgerTable holderId={item.id} kind="package" /></div>
          <div><h3 className="mb-2 text-sm font-semibold">{t("invoices")}</h3><RunsTable ownerId={item.id} companyId={item.company_id} empty={{ title: t("noInvoices") }} /></div>
        </div>
      )}
      <ConfirmDialog open={refunding} onClose={() => setRefunding(false)} danger title={t("refundTitle")} confirmLabel={t("refund")} busy={refund.isPending}
        onConfirm={() => note.trim() && refund.mutate()}
        message={<div className="space-y-3"><p>{t("refundExplain")}</p><Field label={t("whyRefund")} required><Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field></div>} />
      <Modal open={adjusting} onClose={() => setAdjusting(false)} title={t("adjustTitle")} size="sm"
        footer={<><Button variant="secondary" onClick={() => setAdjusting(false)}>{t("cancel")}</Button>
          <Button loading={adjust.isPending} disabled={!amount.trim() || Number(amount) === 0 || !note.trim()} onClick={() => adjust.mutate()}>{t("adjustCredits")}</Button></>}>
        <div className="space-y-4">
          <p className="text-sm text-muted">{t("adjustExplain")}</p>
          <Field label={t("adjustBy")} hint={t("adjustByHint")} required><NumberInput value={amount} onChange={setAmount} /></Field>
          <Field label={t("whyAdjust")} required><Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
        </div>
      </Modal>
    </Drawer>
  );
}
