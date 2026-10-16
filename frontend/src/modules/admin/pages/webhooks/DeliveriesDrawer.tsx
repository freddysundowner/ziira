import { RefreshCw } from "lucide-react";
import { useState } from "react";

import {
  api, Badge, Button, Drawer, EmptyState, ErrorState, formatDate, Select, SkeletonRows, toast, unwrap, useMutation, useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import { canRedeliver, deliveryTone } from "./lib";

type Endpoint = Schemas["WebhookOut"];
type Delivery = Schemas["DeliveryOut"];

/** What was sent to one endpoint: each delivery with its result, its attempts, and a button to send it again. */
export default function DeliveriesDrawer({ endpoint, onClose }: { endpoint: Endpoint | null; onClose: () => void }) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const id = endpoint?.id ?? "";
  const list = useQuery({
    enabled: !!endpoint, queryKey: ["webhook-deliveries", id, status], refetchInterval: 10_000,
    queryFn: () => unwrap(api.GET("/api/v1/webhooks/endpoints/{endpoint_id}/deliveries", { params: { path: { endpoint_id: id }, query: { status: status || undefined, limit: 50 } } })),
  });
  const again = useMutation({
    mutationFn: (d: Delivery) => unwrap(api.POST("/api/v1/webhooks/deliveries/{delivery_id}/redeliver", { params: { path: { delivery_id: d.id } } })),
    onSuccess: () => { toast(t("webhooks.queued"), "ok"); void qc.invalidateQueries({ queryKey: ["webhook-deliveries", id] }); },
  });

  return (
    <Drawer open={!!endpoint} onClose={onClose} title={t("webhooks.deliveriesOf", { name: endpoint?.name })}
      footer={<Button variant="secondary" onClick={() => void list.refetch()} loading={list.isFetching}><RefreshCw className="h-4 w-4" />{t("webhooks.refresh")}</Button>}>
      <div className="mb-3 flex items-center gap-2">
        <Select aria-label={t("webhooks.filterStatus")} className="w-44" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t("webhooks.allStatuses")}</option>
          {["delivered", "pending", "failed", "cancelled"].map((s) => <option key={s} value={s}>{t(`webhooks.status.${s}`)}</option>)}
        </Select>
      </div>
      {list.error ? <ErrorState message={list.error.message} onRetry={() => void list.refetch()} /> : !list.data ? <SkeletonRows rows={5} cols={3} /> : list.data.length === 0 ? (
        <EmptyState title={t("webhooks.noDeliveries")} hint={t("webhooks.noDeliveriesHint")} />
      ) : (
        <ul className="divide-y divide-line rounded-xl border border-line">
          {list.data.map((d) => (
            <li key={d.id}>
              <button type="button" className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-sunken" aria-expanded={openId === d.id} onClick={() => setOpenId(openId === d.id ? null : d.id)}>
                <Badge tone={deliveryTone(d.status)}>{t(`webhooks.status.${d.status}`)}</Badge>
                <span className="min-w-0 flex-1">
                  <code className="block truncate text-xs">{d.event_type}{d.is_test ? ` (${t("webhooks.test")})` : ""}</code>
                  <span className="block truncate text-xs text-muted">{formatDate(d.created_at, true)}</span>
                </span>
                <span className="text-xs text-muted">{d.last_status_code ?? "—"}</span>
              </button>
              {openId === d.id && <DeliveryDetail delivery={d} endpoint={endpoint!} busy={again.isPending} onAgain={() => again.mutate(d)} />}
            </li>
          ))}
        </ul>
      )}
    </Drawer>
  );
}

function DeliveryDetail({ delivery, endpoint, busy, onAgain }: { delivery: Delivery; endpoint: Endpoint; busy: boolean; onAgain: () => void }) {
  const { t } = useTranslation("kernel");
  const detail = useQuery({ queryKey: ["webhook-delivery", delivery.id, delivery.attempts, delivery.status], queryFn: () => unwrap(api.GET("/api/v1/webhooks/deliveries/{delivery_id}", { params: { path: { delivery_id: delivery.id } } })) });
  return (
    <div className="space-y-3 bg-sunken/50 px-3 py-3 text-xs">
      {detail.error ? <ErrorState message={detail.error.message} onRetry={() => void detail.refetch()} /> : !detail.data ? <SkeletonRows rows={2} cols={2} /> : (
        <>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
            <dt className="text-muted">{t("webhooks.eventId")}</dt><dd className="break-all font-mono">{detail.data.event_id}</dd>
            <dt className="text-muted">{t("webhooks.attempts")}</dt><dd>{detail.data.attempts} / {detail.data.max_attempts}</dd>
            {detail.data.next_attempt_at && <><dt className="text-muted">{t("webhooks.nextTry")}</dt><dd>{formatDate(detail.data.next_attempt_at, true)}</dd></>}
            <dt className="text-muted">{t("webhooks.size")}</dt><dd>{detail.data.body_bytes} B · sha256 <span className="break-all font-mono">{detail.data.body_sha256.slice(0, 16)}…</span></dd>
          </dl>
          <div>
            <p className="mb-1 font-medium">{t("webhooks.firstBytes")}</p>
            <pre className="max-h-28 overflow-auto whitespace-pre-wrap break-all rounded-lg border border-line bg-surface p-2 font-mono">{detail.data.body_preview}</pre>
          </div>
          <div>
            <p className="mb-1 font-medium">{t("webhooks.attemptLog")}</p>
            <ul className="space-y-1">
              {detail.data.attempt_log.map((a, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2">
                  <Badge tone={a.ok ? "ok" : "bad"}>{a.status_code ?? "—"}</Badge>
                  <span>{formatDate(a.attempted_at, true)}</span>
                  <span className="text-muted">{a.duration_ms ?? 0} ms{a.error ? ` · ${a.error}` : ""}</span>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
      {canRedeliver(delivery, endpoint)
        ? <Button size="sm" variant="secondary" loading={busy} onClick={onAgain}>{t("webhooks.redeliver")}</Button>
        : delivery.status !== "pending" && !delivery.has_body && <p className="text-muted">{t("webhooks.contentGone")}</p>}
    </div>
  );
}
