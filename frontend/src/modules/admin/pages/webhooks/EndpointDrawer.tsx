import { type FormEvent, useEffect, useMemo, useState } from "react";

import {
  api, Button, Checkbox, Drawer, ErrorState, Field, Input, Alert, SkeletonRows, humanise, toast, unwrap, useFormState, useMutation, useQuery, useQueryClient, useTranslation, type Schemas,
} from "@/sdk";

import { groupEvents, toggleEvent } from "./lib";

type Endpoint = Schemas["WebhookOut"];

/** Add a webhook endpoint, or change one. Creating gives back the signing secret, which the page shows once. */
export default function EndpointDrawer({ open, endpoint, onClose, onCreated }: {
  open: boolean; endpoint: Endpoint | null; onClose: () => void; onCreated: (name: string, secret: string) => void;
}) {
  const { t } = useTranslation("kernel");
  const qc = useQueryClient();
  const catalogue = useQuery({ enabled: open, queryKey: ["webhook-events"], queryFn: () => unwrap(api.GET("/api/v1/webhooks/events")) });
  const groups = useMemo(() => groupEvents(catalogue.data ?? []), [catalogue.data]);
  const f = useFormState({ name: "", url: "" });
  const [events, setEvents] = useState<string[]>([]);
  useEffect(() => {
    if (!open) return;
    f.set("name", endpoint?.name ?? ""); f.set("url", endpoint?.url ?? ""); setEvents(endpoint?.event_types ?? []);
    // Only when the drawer opens or a different endpoint is chosen.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, endpoint?.id]);

  const save = useMutation({
    meta: { silent: true },
    mutationFn: async () => {
      const body = { name: f.values.name.trim(), url: f.values.url.trim(), event_types: events };
      if (endpoint) {
        await unwrap(api.PATCH("/api/v1/webhooks/endpoints/{endpoint_id}", { params: { path: { endpoint_id: endpoint.id } }, body }));
        return null;
      }
      return unwrap(api.POST("/api/v1/webhooks/endpoints", { body }));
    },
    onSuccess: (created) => {
      void qc.invalidateQueries({ queryKey: ["webhooks"] });
      if (created) onCreated(created.endpoint.name, created.secret); else { toast(t("webhooks.saved"), "ok"); onClose(); }
    },
    onError: (e) => { f.fail(e); toast(e.message, "bad"); },
  });
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate(); };

  return (
    <Drawer open={open} onClose={onClose} title={endpoint ? t("webhooks.edit") : t("webhooks.new")}
      footer={<><Button variant="secondary" onClick={onClose}>{t("cancel")}</Button>
        <Button type="submit" form="webhook-form" loading={save.isPending} disabled={events.length === 0}>{endpoint ? t("webhooks.saveChanges") : t("webhooks.create")}</Button></>}>
      <form id="webhook-form" onSubmit={submit} className="space-y-5">
        <Field label={t("webhooks.name")} hint={t("webhooks.nameHint")} required error={f.error("name")}><Input {...f.bind("name")} required maxLength={120} autoFocus /></Field>
        <Field label={t("webhooks.url")} hint={t("webhooks.urlHint")} required error={f.error("url")}>
          <Input type="url" {...f.bind("url")} required maxLength={2000} placeholder="https://" inputMode="url" autoComplete="off" spellCheck={false} />
        </Field>
        <div>
          <p className="mb-1 text-sm font-medium">{t("webhooks.events")}</p>
          <p className="mb-3 text-xs text-muted">{t("webhooks.eventsHint")}</p>
          {catalogue.error ? <ErrorState message={catalogue.error.message} onRetry={() => void catalogue.refetch()} /> : !catalogue.data ? <SkeletonRows rows={4} cols={2} /> : (
            <div className="space-y-3">
              {groups.map((g) => (
                <fieldset key={g.unit} className="rounded-xl border border-line p-3">
                  <legend className="px-1 text-sm font-semibold">{humanise(g.unit)}</legend>
                  <div className="space-y-2">
                    {g.events.map((ev) => (
                      <div key={ev.type}>
                        <Checkbox checked={events.includes(ev.type)} onChange={(e) => setEvents(toggleEvent(events, ev.type, e.target.checked))}
                          label={<span><code className="text-xs">{ev.type}</code> <span className="text-muted">{ev.description}</span></span>} />
                        <p className="ml-6 text-xs text-muted">{t("webhooks.sends", { fields: ev.fields.join(", ") })}</p>
                      </div>
                    ))}
                  </div>
                </fieldset>
              ))}
            </div>
          )}
          {f.error("event_types") && <p role="alert" className="mt-1 text-xs text-bad">{f.error("event_types")}</p>}
        </div>
        {!endpoint && <Alert tone="info">{t("webhooks.secretNote")}</Alert>}
      </form>
    </Drawer>
  );
}
