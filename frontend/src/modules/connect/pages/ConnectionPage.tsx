import { useState } from "react";
import { useLocation, useParams } from "react-router-dom";

import {
  Alert, api, Badge, Button, Card, Checkbox, ConfirmDialog, DataTable, DetailList, ErrorState, PageHeader, Skeleton, Tabs, toast, unwrap, useCan, useMutation, useQuery, useQueryClient, useTranslation,
} from "@/sdk";

import { BranchMapping } from "../components/BranchMapping";
import { OAuthButton } from "../components/OAuthButton";
import { RunsTable, when } from "../components/RunsTable";
import { SettingsForm } from "../components/SettingsForm";
import { StatusChip } from "../components/StatusChip";
import { UploadFlow } from "../components/UploadFlow";
import { isStale, oauthResult, sortEntities } from "../logic";

type Tab = "overview" | "history" | "branches" | "upload" | "settings";

/** One connected system: status, what has been read, history with errors, branches, uploads, settings. */
export default function ConnectionPage() {
  const { t } = useTranslation("connect");
  const { connectionId = "" } = useParams();
  const { search } = useLocation();
  const queryClient = useQueryClient();
  const canManage = useCan("connect.manage");
  const [tab, setTab] = useState<Tab>("overview");
  const [confirm, setConfirm] = useState(false);
  const [deleteData, setDeleteData] = useState(false);
  const key = ["connect", "connection", connectionId];
  const query = useQuery({ queryKey: key, queryFn: () => unwrap(api.GET("/api/v1/connect/connections/{connection_id}", { params: { path: { connection_id: connectionId } } })), refetchInterval: 15_000 });
  const kinds = useQuery({ queryKey: ["connect", "kinds"], queryFn: () => unwrap(api.GET("/api/v1/connect/kinds")) });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["connect"] });
  const path = { params: { path: { connection_id: connectionId } } };

  const sync = useMutation({
    meta: { silent: true },
    mutationFn: (full: boolean) => unwrap(api.POST("/api/v1/connect/connections/{connection_id}/sync", { ...path, body: { full } })),
    onSuccess: (r) => { toast(r.queued ? t("overview.queued") : t("overview.alreadyQueued"), "ok"); refresh(); },
    onError: (e) => toast(e.message, "bad"),
  });
  const pause = useMutation({ meta: { silent: true }, mutationFn: () => unwrap(api.POST("/api/v1/connect/connections/{connection_id}/pause", path)), onSuccess: refresh, onError: (e) => toast(e.message, "bad") });
  const resume = useMutation({ meta: { silent: true }, mutationFn: () => unwrap(api.POST("/api/v1/connect/connections/{connection_id}/resume", path)), onSuccess: refresh, onError: (e) => toast(e.message, "bad") });
  const test = useMutation({ meta: { silent: true }, mutationFn: () => unwrap(api.POST("/api/v1/connect/connections/{connection_id}/test", path)) });
  const disconnect = useMutation({
    meta: { silent: true },
    mutationFn: () => unwrap(api.POST("/api/v1/connect/connections/{connection_id}/disconnect", { ...path, body: { delete_data: deleteData } })),
    onSuccess: () => { setConfirm(false); toast(t("disconnect.done"), "ok"); refresh(); },
    onError: (e) => toast(e.message, "bad"),
  });

  if (query.isLoading) return <Skeleton className="h-64 w-full" />;
  if (query.error || !query.data) return <ErrorState message={query.error?.message} onRetry={() => void query.refetch()} />;
  const c = query.data;
  const kind = kinds.data?.find((k) => k.kind === c.kind);
  const isFile = c.freshness === "on_upload";
  const oauth = oauthResult(search);
  const disconnected = c.status === "disconnected";
  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: t("tab.overview") }, { id: "history", label: t("tab.history") }, { id: "branches", label: t("tab.branches"), count: c.unmapped_branches || undefined } as { id: Tab; label: string },
    ...(isFile && canManage && !disconnected ? [{ id: "upload" as Tab, label: t("tab.upload") }] : []),
    ...(canManage ? [{ id: "settings" as Tab, label: t("tab.settings") }] : []),
  ];

  return (
    <>
      <PageHeader title={c.name} description={c.kind_title} back={{ to: "/connect", label: t("title") }}
        actions={canManage && !disconnected && (
          <>
            {!isFile && <Button loading={sync.isPending} onClick={() => sync.mutate(false)}>{t("overview.syncNow")}</Button>}
            {c.status === "paused" ? <Button variant="secondary" loading={resume.isPending} onClick={() => resume.mutate()}>{t("overview.resume")}</Button>
              : <Button variant="secondary" loading={pause.isPending} onClick={() => pause.mutate()}>{t("overview.pause")}</Button>}
            <Button variant="danger" onClick={() => setConfirm(true)}>{t("disconnect.button")}</Button>
          </>
        )} />
      {oauth && <Alert tone={oauth.ok ? "ok" : "bad"} className="mb-4">{oauth.ok ? t("oauth.success") : t("oauth.failed", { reason: t(`oauth.reason.${oauth.reason}`, { defaultValue: oauth.reason ?? "" }) })}</Alert>}
      <Tabs tabs={tabs} value={tab} onChange={setTab} />

      {tab === "overview" && (
        <div className="space-y-4">
          {c.last_error && c.status !== "disconnected" && (
            <Alert tone="bad">
              <p>{c.last_error}</p>
              {canManage && !isFile && <Button size="sm" variant="secondary" className="mt-2" loading={sync.isPending} onClick={() => sync.mutate(false)}>{t("overview.retry")}</Button>}
            </Alert>
          )}
          {isStale(c) && <Alert tone="warn">{t("overview.stale")}</Alert>}
          {c.needs_oauth && canManage && !disconnected && (
            <Card title={t("oauth.title")}><OAuthButton connectionId={c.id} kind={c.kind} title={c.kind_title} authorised={c.secrets_set.length > 0} /></Card>
          )}
          <Card title={t("overview.status")}>
            <DetailList items={[
              { label: t("list.status"), value: <StatusChip status={c.status} /> },
              { label: t("list.freshness"), value: t(`freshness.${c.freshness}`) },
              { label: t("overview.lastRead"), value: when(c.last_sync_at) },
              { label: t("overview.lastSuccess"), value: when(c.last_success_at) },
              ...(isFile ? [] : [{ label: t("overview.next"), value: when(c.next_sync_at) }]),
              { label: t("overview.failures"), value: <span className="tnum">{c.failures}</span> },
            ]} />
            {canManage && !disconnected && (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <Button variant="secondary" size="sm" loading={test.isPending} onClick={() => test.mutate()}>{t("overview.test")}</Button>
                {!isFile && <Button variant="ghost" size="sm" loading={sync.isPending} onClick={() => sync.mutate(true)}>{t("overview.full")}</Button>}
                {test.data && <Badge tone={test.data.ok ? "ok" : "bad"}>{test.data.message}</Badge>}
                {test.error && <Badge tone="bad">{test.error.message}</Badge>}
              </div>
            )}
          </Card>
          <Card title={t("overview.reads")} flush>
            <DataTable
              rows={sortEntities(c.entities.map((e) => e.entity)).map((e) => c.entities.find((x) => x.entity === e)!)} rowKey={(e) => e.entity}
              empty={{ title: t("overview.noEntities") }}
              columns={[
                { header: t("history.entity"), cell: (e) => t(`entity.${e.entity}`, { defaultValue: e.entity }) },
                { header: t("overview.rows"), align: "right", cell: (e) => <span className="tnum">{c.counts[e.entity] ?? 0}</span> },
                { header: t("overview.completeAt"), hideBelow: "sm", cell: (e) => e.complete_at ? when(e.complete_at) : <Badge tone="warn">{t("overview.notYet")}</Badge> },
                { header: t("overview.through"), hideBelow: "md", cell: (e) => when(e.data_through) },
              ]}
            />
          </Card>
        </div>
      )}
      {tab === "history" && <Card flush><RunsTable connectionId={c.id} /></Card>}
      {tab === "branches" && <Card><BranchMapping connectionId={c.id} companyId={c.company_id} /></Card>}
      {tab === "upload" && kind && <UploadFlow connectionId={c.id} kind={kind} companyId={c.company_id} onDone={refresh} />}
      {tab === "settings" && <Card><SettingsForm connection={c} kind={kind} /></Card>}

      <ConfirmDialog open={confirm} onClose={() => setConfirm(false)} onConfirm={() => disconnect.mutate()} danger busy={disconnect.isPending}
        title={t("disconnect.title", { name: c.name })} confirmLabel={t("disconnect.confirm")}
        message={<div className="space-y-3"><p>{t("disconnect.message")}</p><Checkbox checked={deleteData} onChange={(e) => setDeleteData(e.target.checked)} label={t("disconnect.deleteData")} /></div>} />
    </>
  );
}
