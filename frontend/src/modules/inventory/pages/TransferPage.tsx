import { useState } from "react";
import { useParams } from "react-router-dom";

import {
  Alert, api, Button, Card, ConfirmDialog, DataTable, DetailList, formatDate, Modal, NumberInput, PageHeader, quantity, type Schemas, Select, toast, unwrap, useCan, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { DocShell } from "../components/DocShell";
import { DocStatus } from "../components/DocStatus";
import { differs } from "../logic";
import { ProductName, useLocations, useReasons } from "../lookups";

type Action = "dispatch" | "cancel";
type Transfer = Schemas["TransferOut"];

/** One transfer: dispatch it, receive it (with a reason for any difference), or cancel a draft. */
export default function TransferPage() {
  const { t } = useTranslation("inventory");
  const { transferId = "" } = useParams();
  const qc = useQueryClient();
  const canTransfer = useCan("stock.transfer");
  const [confirm, setConfirm] = useState<Action | null>(null);
  const [receiving, setReceiving] = useState(false);
  const locations = useLocations();
  const doc = useQuery({
    queryKey: ["inv-transfer", transferId],
    queryFn: () => unwrap(api.GET("/api/v1/inventory/transfers/{transfer_id}", { params: { path: { transfer_id: transferId } } })),
  });
  const x = doc.data;
  const place = (id: string) => locations.data?.find((l) => l.id === id)?.name ?? "—";

  function done(next: Transfer, message: string) {
    qc.setQueryData(["inv-transfer", transferId], next);
    for (const key of ["inv-transfers", "inv-balances", "inv-range-balances", "inv-movements"]) void qc.invalidateQueries({ queryKey: [key] });
    toast(message, next.status === "pending_approval" ? "info" : "ok");
    setConfirm(null);
    setReceiving(false);
  }
  const act = useMutation({
    mutationFn: (a: Action) => unwrap(api.POST(a === "dispatch" ? "/api/v1/inventory/transfers/{transfer_id}/dispatch" : "/api/v1/inventory/transfers/{transfer_id}/cancel", { params: { path: { transfer_id: transferId } } })),
    onSuccess: (next, a) => done(next, a === "dispatch" ? t("transferDispatched") : t("transferCancelled")),
    onError: () => setConfirm(null),
  });

  return (
    <DocShell loading={!x} error={doc.error?.message} onRetry={() => void doc.refetch()}>
      {x && (
        <>
          <PageHeader back={{ to: "/stock/transfers", label: t("transfers") }} title={x.number} description={<DocStatus status={x.status} />}
            actions={canTransfer && (
              <>
                {x.status === "draft" && <Button variant="secondary" onClick={() => setConfirm("cancel")}>{t("cancelTransfer")}</Button>}
                {x.status === "draft" && <Button onClick={() => setConfirm("dispatch")}>{t("dispatch")}</Button>}
                {x.status === "dispatched" && <Button onClick={() => setReceiving(true)}>{t("receive")}</Button>}
              </>
            )} />
          {x.status === "draft" && <Alert className="mb-4">{t("transferDraftNote")}</Alert>}
          {x.status === "dispatched" && <Alert className="mb-4">{t("transferOnTheWay")}</Alert>}
          {x.status === "pending_approval" && <Alert tone="warn" className="mb-4">{t("waitingApproval")}</Alert>}
          <div className="space-y-4">
            <Card>
              <DetailList items={[
                { label: t("from"), value: place(x.from_location_id) },
                { label: t("to"), value: place(x.to_location_id) },
                { label: t("dispatchedOn"), value: formatDate(x.dispatched_at, true) },
                { label: t("receivedOn"), value: formatDate(x.received_at, true) },
              ]} />
            </Card>
            <DataTable rows={x.lines} rowKey={(l) => l.id} empty={{ title: t("noLines") }}
              columns={[
                { header: t("product"), cell: (l) => <ProductName id={l.product_id} /> },
                { header: t("qtySent"), align: "right", cell: (l) => quantity(l.qty_sent) },
                { header: t("qtyReceived"), align: "right", cell: (l) => (l.qty_received === null ? "—" : <span className={differs(l.qty_sent, l.qty_received) ? "font-medium text-warn" : ""}>{quantity(l.qty_received)}</span>) },
              ]} />
          </div>
          <ConfirmDialog open={confirm !== null} onClose={() => setConfirm(null)} busy={act.isPending} danger={confirm === "cancel"}
            onConfirm={() => confirm && act.mutate(confirm)} confirmLabel={confirm === "cancel" ? t("cancelTransfer") : t("dispatch")}
            title={confirm === "cancel" ? t("cancelTransfer") : t("dispatch")} message={confirm === "cancel" ? t("cancelTransferAsk") : t("dispatchAsk")} />
          <ReceiveModal open={receiving} onClose={() => setReceiving(false)} transfer={x} onDone={(next) => done(next, next.status === "pending_approval" ? t("sentForApproval") : t("transferReceived"))} />
        </>
      )}
    </DocShell>
  );
}

function ReceiveModal({ open, onClose, transfer, onDone }: { open: boolean; onClose: () => void; transfer: Transfer; onDone: (t: Transfer) => void }) {
  const { t } = useTranslation("inventory");
  const reasons = useReasons("transfer_variance", open);
  const [received, setReceived] = useState<Record<string, string>>({});
  const [why, setWhy] = useState<Record<string, string>>({});
  const value = (id: string, sent: string) => received[id] ?? sent;
  const reasonFor = (id: string) => why[id] ?? reasons.data?.[0]?.id ?? "";
  const anyDifference = transfer.lines.some((l) => differs(l.qty_sent, value(l.id, l.qty_sent)));

  const save = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/inventory/transfers/{transfer_id}/receive", {
      params: { path: { transfer_id: transfer.id } },
      body: anyDifference ? { lines: transfer.lines.map((l) => ({
        line_id: l.id, qty_received: value(l.id, l.qty_sent),
        reason_code_id: differs(l.qty_sent, value(l.id, l.qty_sent)) ? reasonFor(l.id) || null : null })) } : undefined })),
    onSuccess: onDone,
  });

  return (
    <Modal open={open} onClose={onClose} title={t("receiveTransfer")} size="lg"
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button><Button loading={save.isPending} onClick={() => save.mutate()}>{anyDifference ? t("receiveWithDifferences") : t("receiveAll")}</Button></>}>
      <p className="mb-3 text-sm text-muted">{t("receiveHint")}</p>
      <div className="space-y-3">
        {transfer.lines.map((l) => {
          const differing = differs(l.qty_sent, value(l.id, l.qty_sent));
          return (
            <div key={l.id} className="rounded-lg border border-line p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <ProductName id={l.product_id} />
                <span className="text-xs text-muted">{t("qtySent")}: {quantity(l.qty_sent)}</span>
              </div>
              <div className="mt-2 grid gap-2 sm:grid-cols-2">
                <NumberInput aria-label={t("qtyReceived")} value={value(l.id, l.qty_sent)} onChange={(v) => setReceived({ ...received, [l.id]: v })} />
                {differing && (
                  <Select aria-label={t("reason")} value={reasonFor(l.id)} onChange={(e) => setWhy({ ...why, [l.id]: e.target.value })}>
                    {(reasons.data ?? []).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
                  </Select>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Modal>
  );
}
