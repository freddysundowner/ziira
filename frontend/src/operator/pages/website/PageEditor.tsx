import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { Alert, Badge, Button, Card, ConfirmDialog, ErrorState, Field, Input, Skeleton, StatusBadge, Tabs, Textarea, toast, useTranslation, useUnsavedWarning } from "@/sdk";

import { opApi, OperatorApiError, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";
import { KEYS, useAssets } from "./api";
import { countTone, imageSnippet, PAGE_STATE_TONE, SEO_LIMITS } from "./model";
import { SafePreview } from "./SafePreview";
import { VersionsPanel } from "./VersionsPanel";

interface Draft { title: string; body: string; seoTitle: string; seoDescription: string; note: string }

/** One page: Markdown on the left with a safe preview, the search fields, mark published / draft, history and delete. */
export function PageEditor({ pageId, onBack }: { pageId: string; onBack: () => void }) {
  const { t } = useTranslation("operator");
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"write" | "preview" | "history">("write");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [stale, setStale] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const page = useQuery({ queryKey: KEYS.page(pageId), queryFn: () => opUnwrap(opApi.GET("/api/v1/operator/site/pages/{page_id}", { params: { path: { page_id: pageId } } })) });
  const assets = useAssets();
  const data = page.data;

  useEffect(() => {
    if (data && draft === null) setDraft({ title: data.title, body: data.body_md, seoTitle: data.seo_title ?? "", seoDescription: data.seo_description ?? "", note: "" });
  }, [data, draft]);

  const dirty = !!data && !!draft && (draft.title !== data.title || draft.body !== data.body_md || draft.seoTitle !== (data.seo_title ?? "") || draft.seoDescription !== (data.seo_description ?? ""));
  useUnsavedWarning(dirty);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["operator", "site"] });
    setDraft(null);
    setStale(false);
  };

  const save = useChange(
    () => opUnwrap(opApi.PUT("/api/v1/operator/site/pages/{page_id}", {
      params: { path: { page_id: pageId } },
      body: { expected_version: data!.version, title: draft!.title, body_md: draft!.body, seo_title: draft!.seoTitle || null, seo_description: draft!.seoDescription || null, note: draft!.note || null },
    })),
    {
      onSuccess: () => { toast(t("website.saved"), "ok"); refresh(); },
      onError: (e) => {
        if (e instanceof OperatorApiError && e.status === 409) setStale(true);
        else toast(e.message, "bad");
      },
    },
  );
  const status = useChange(
    (to: "publish" | "unpublish") => opUnwrap(opApi.POST(to === "publish" ? "/api/v1/operator/site/pages/{page_id}/publish" : "/api/v1/operator/site/pages/{page_id}/unpublish", { params: { path: { page_id: pageId } } })),
    { onSuccess: (_p, to) => { toast(t(to === "publish" ? "website.pages.markedPublished" : "website.pages.markedDraft"), "ok"); refresh(); } },
  );
  const remove = useChange(
    () => opUnwrap(opApi.DELETE("/api/v1/operator/site/pages/{page_id}", { params: { path: { page_id: pageId } } })),
    {
      onSuccess: () => { toast(t("website.pages.deleted"), "ok"); void queryClient.invalidateQueries({ queryKey: ["operator", "site"] }); onBack(); },
      onError: (e) => { toast(e.message, "bad"); setConfirmDelete(false); },
    },
  );

  const snippets = useMemo(() => (assets.data ?? []).slice(0, 12), [assets.data]);
  if (page.isPending || (data && !draft)) return <Skeleton className="h-96 w-full" />;
  if (page.isError || !data || !draft) return <ErrorState message={page.error?.message} onRetry={() => void page.refetch()} />;
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <Button variant="ghost" size="sm" onClick={onBack}>{t("website.pages.back")}</Button>
          <h2 className="mt-1 text-lg font-semibold">{data.title}</h2>
          <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <span className="font-mono">{data.locale}/{data.slug}</span>
            <StatusBadge status={data.status} />
            <Badge tone={PAGE_STATE_TONE[data.state] ?? "neutral"}>{t(`website.pages.states.${data.state}`)}</Badge>
            <span>{t("website.pages.version", { version: data.version })}</span>
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {data.status === "draft"
            ? <Button variant="secondary" loading={status.isPending} disabled={dirty} onClick={() => status.mutate("publish")}>{t("website.pages.markPublished")}</Button>
            : <Button variant="secondary" loading={status.isPending} disabled={dirty} onClick={() => status.mutate("unpublish")}>{t("website.pages.markDraft")}</Button>}
          {data.status === "draft" && <Button variant="danger" onClick={() => setConfirmDelete(true)}>{t("website.pages.delete")}</Button>}
          <Button loading={save.isPending} disabled={!dirty || stale || !draft.title.trim()} onClick={() => save.mutate(undefined)}>{t("website.save")}</Button>
        </div>
      </div>
      {data.status === "published" && <Alert tone="info">{t("website.pages.publishedNote")}</Alert>}
      {stale && <Alert tone="warn"><div className="flex flex-wrap items-center justify-between gap-2"><span>{t("website.pages.stale")}</span><Button size="sm" variant="secondary" onClick={refresh}>{t("website.pages.reload")}</Button></div></Alert>}

      <Tabs tabs={[{ id: "write", label: t("website.pages.write") }, { id: "preview", label: t("website.pages.preview") }, { id: "history", label: t("website.pages.history") }]} value={tab} onChange={setTab} />
      {tab === "write" && (
        <div className="grid gap-4 xl:grid-cols-2">
          <div className="space-y-3">
            <Field label={t("website.pages.title")} required><Input value={draft.title} maxLength={160} onChange={(e) => set({ title: e.target.value })} /></Field>
            <Field label={t("website.pages.body")} hint={t("website.pages.bodyHint")}>
              <Textarea value={draft.body} rows={20} spellCheck className="font-mono text-[13px] leading-relaxed" onChange={(e) => set({ body: e.target.value })} />
            </Field>
            {snippets.length > 0 && (
              <details className="rounded-lg border border-line p-3 text-sm">
                <summary className="cursor-pointer font-medium">{t("website.pages.pictures")}</summary>
                <ul className="mt-2 space-y-1">
                  {snippets.map((a) => (
                    <li key={a.id} className="flex items-center justify-between gap-2">
                      <span className="truncate">{a.name}</span>
                      <Button size="sm" variant="secondary" onClick={() => set({ body: `${draft.body}${draft.body.endsWith("\n") || !draft.body ? "" : "\n"}${imageSnippet(a.asset_id, a.alt || a.name)}\n` })}>{t("website.pages.insert")}</Button>
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <Field label={t("website.pages.note")} hint={t("website.pages.noteHint")}><Input value={draft.note} maxLength={300} onChange={(e) => set({ note: e.target.value })} /></Field>
          </div>
          <div className="space-y-3">
            <Card title={t("website.pages.seo")}>
              <div className="space-y-3">
                <Field label={t("website.pages.seoTitle")} hint={`${draft.seoTitle.length}/${SEO_LIMITS.title}`}>
                  <Input value={draft.seoTitle} maxLength={120} className={countTone(draft.seoTitle.length, SEO_LIMITS.title) === "warn" ? "border-warn" : ""} onChange={(e) => set({ seoTitle: e.target.value })} />
                </Field>
                <Field label={t("website.pages.seoDescription")} hint={`${draft.seoDescription.length}/${SEO_LIMITS.description}`}>
                  <Textarea value={draft.seoDescription} rows={3} maxLength={300} onChange={(e) => set({ seoDescription: e.target.value })} />
                </Field>
              </div>
            </Card>
            <SafePreview markdown={draft.body} />
          </div>
        </div>
      )}
      {tab === "preview" && <SafePreview markdown={draft.body} />}
      {tab === "history" && <VersionsPanel pageId={pageId} current={data.version} onRestored={refresh} />}
      <ConfirmDialog open={confirmDelete} onClose={() => setConfirmDelete(false)} busy={remove.isPending} danger title={t("website.pages.deleteTitle")}
        message={t("website.pages.deleteMessage")} confirmLabel={t("website.pages.delete")} onConfirm={() => remove.mutate(undefined)} />
    </div>
  );
}
