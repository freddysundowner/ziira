import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, Badge, Button, Card, type Column, DataTable, ErrorState, Field, formatDate, Input, Modal, type Schemas, Skeleton, toast, useTranslation } from "@/sdk";

import { opApi, OperatorApiError, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";
import { KEYS, useSiteStatus } from "./api";
import { groupIssues } from "./model";

type Line = Schemas["SitePublishLine"];
type Issue = Schemas["SiteIssue"];
const HOOK_TONE = { ok: "ok", failed: "bad", pending: "warn", skipped: "neutral" } as const;

function Issues({ issues, tone }: { issues: Issue[]; tone: "bad" | "warn" }) {
  const { t } = useTranslation("operator");
  return (
    <div className="space-y-3">
      {groupIssues(issues).map(([code, list]) => (
        <div key={code}>
          <p className="mb-1 text-sm font-medium"><Badge tone={tone}>{list.length}</Badge> {t(`website.publish.codes.${code}`, { defaultValue: code })}</p>
          <ul className="space-y-0.5 pl-1 text-sm">{list.map((i) => <li key={`${i.where}${i.message}`}><span className="font-mono text-xs text-muted">{i.where}</span> {i.message}</li>)}</ul>
        </div>
      ))}
    </div>
  );
}

/** Check, review what will change, publish (explicit, with a note), and follow the site rebuild. */
export default function PublishTab() {
  const { t } = useTranslation("operator");
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);
  const [note, setNote] = useState("");
  const [blocked, setBlocked] = useState<Schemas["SiteReport"] | null>(null);
  const report = useQuery({ queryKey: KEYS.validate, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/site/validate")), staleTime: 0 });
  const status = useSiteStatus();
  const history = useQuery({ queryKey: KEYS.publishes, queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/site/publishes")), refetchInterval: (q) => (q.state.data?.some((l) => l.hook_status === "pending") ? 15_000 : false) });

  const refresh = () => { void queryClient.invalidateQueries({ queryKey: ["operator", "site"] }); };
  const publish = useChange(
    () => opUnwrap(opApi.POST("/api/v1/operator/site/publish", { body: { note: note.trim() || null } })),
    {
      onSuccess: () => { toast(t("website.publish.done"), "ok"); setConfirming(false); setNote(""); setBlocked(null); refresh(); },
      onError: (e) => {
        setConfirming(false);
        if (e instanceof OperatorApiError && e.body.report) { setBlocked(e.body.report as Schemas["SiteReport"]); refresh(); }
        else toast(e.message, "bad");
      },
    },
  );
  const retry = useChange(
    (id: number) => opUnwrap(opApi.POST("/api/v1/operator/site/publishes/{publish_id}/retry-hook", { params: { path: { publish_id: id } } })),
    { onSuccess: (state) => { toast(t(`website.publish.retried.${state.hook_status}`, { defaultValue: state.hook_status }), state.hook_status === "ok" ? "ok" : "warn"); refresh(); }, onError: (e) => toast(e.message, "bad") },
  );

  const shown = blocked ?? report.data;
  const pending = status.data?.pending ?? [];
  const live = status.data?.live;
  const columns: Column<Line>[] = [
    { header: t("website.publish.when"), cell: (l) => <div className="text-sm">{formatDate(l.published_at, true)}<p className="text-xs text-muted">{l.published_by}</p></div> },
    { header: t("website.publish.note"), hideBelow: "sm", cell: (l) => <span className="text-sm">{l.note ?? ""}</span> },
    { header: t("website.publish.pages"), align: "right", hideBelow: "md", cell: (l) => <span className="tnum text-sm">{l.pages}</span> },
    { header: t("website.publish.rebuild"), cell: (l) => (
      <div>
        <Badge tone={HOOK_TONE[l.hook_status as keyof typeof HOOK_TONE] ?? "neutral"}>{t(`website.publish.hook.${l.hook_status}`)}</Badge>
        {l.hook_result && <p className="mt-0.5 text-xs text-muted">{l.hook_result}{l.hook_attempts > 1 ? ` (${l.hook_attempts})` : ""}</p>}
      </div>
    ) },
    { header: "", align: "right", cell: (l) => (l.hook_status === "failed" || l.hook_status === "pending") ? <Button size="sm" variant="secondary" loading={retry.isPending && retry.variables === l.id} onClick={() => retry.mutate(l.id)}>{t("website.publish.retry")}</Button> : null },
  ];

  return (
    <div className="space-y-4">
      <Card title={t("website.publish.state")}>
        {status.isError ? <ErrorState message={status.error.message} onRetry={() => void status.refetch()} /> : status.isPending ? <Skeleton className="h-12 w-full" /> : (
          <div className="space-y-3">
            <p className="text-sm">{live ? t("website.publish.live", { when: formatDate(live.published_at, true), who: live.published_by }) : t("website.publish.neverPublished")}</p>
            {pending.length === 0
              ? <Alert tone="ok">{t("website.publish.noChanges")}</Alert>
              : <Alert tone="warn"><p className="font-medium">{t("website.publish.pendingTitle", { count: pending.length })}</p>
                  <ul className="mt-1 list-disc pl-4 text-sm">{pending.map((p) => <li key={`${p.area}${p.ref}`}>{t(`website.publish.change.${p.area}`, { ref: p.ref })} - {t(`website.publish.changeKind.${p.change}`)}</li>)}</ul></Alert>}
            {status.data && !status.data.hook_configured && <p className="text-xs text-muted">{t("website.publish.noHook")}</p>}
          </div>
        )}
      </Card>

      <Card title={t("website.publish.checkTitle")} description={t("website.publish.checkHint")}
        actions={<Button variant="secondary" size="sm" loading={report.isFetching} onClick={() => { setBlocked(null); void report.refetch(); }}>{t("website.publish.recheck")}</Button>}>
        {report.isPending ? <Skeleton className="h-20 w-full" /> : report.isError ? <ErrorState message={report.error.message} onRetry={() => void report.refetch()} /> : shown && (
          <div className="space-y-4">
            {shown.ok ? <Alert tone="ok">{t("website.publish.ready")}</Alert> : <Alert tone="bad">{t("website.publish.notReady", { count: shown.errors.length })}</Alert>}
            {shown.errors.length > 0 && <Issues issues={shown.errors} tone="bad" />}
            {shown.warnings.length > 0 && (
              <details className="rounded-lg border border-line p-3"><summary className="cursor-pointer text-sm font-medium">{t("website.publish.warnings", { count: shown.warnings.length })}</summary><div className="mt-3"><Issues issues={shown.warnings} tone="warn" /></div></details>
            )}
          </div>
        )}
        <div className="mt-4 flex justify-end">
          <Button disabled={!shown?.ok || pending.length === 0} onClick={() => setConfirming(true)}>{t("website.publish.button")}</Button>
        </div>
      </Card>

      <div>
        <h2 className="mb-2 text-base font-semibold">{t("website.publish.history")}</h2>
        <DataTable rows={history.data} columns={columns} rowKey={(l) => String(l.id)} loading={history.isPending} error={history.isError ? history.error.message : null}
          onRetry={() => void history.refetch()} dense pageSize={10} empty={{ title: t("website.publish.historyEmpty"), hint: t("website.publish.historyEmptyHint") }} />
      </div>

      <Modal open={confirming} onClose={() => setConfirming(false)} title={t("website.publish.confirmTitle")} size="md"
        footer={<><Button variant="secondary" onClick={() => setConfirming(false)}>{t("cancel")}</Button><Button loading={publish.isPending} onClick={() => publish.mutate(undefined)}>{t("website.publish.button")}</Button></>}>
        <div className="space-y-3 text-sm">
          <p>{t("website.publish.confirmBody")}</p>
          <ul className="list-disc pl-4 text-muted">{pending.map((p) => <li key={`${p.area}${p.ref}`}>{t(`website.publish.change.${p.area}`, { ref: p.ref })} - {t(`website.publish.changeKind.${p.change}`)}</li>)}</ul>
          <Field label={t("website.publish.noteLabel")} hint={t("website.publish.noteHint")}><Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} /></Field>
        </div>
      </Modal>
    </div>
  );
}
