import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { Alert, Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, Field, Input, type Schemas, Skeleton, toast, useTranslation } from "@/sdk";

import { opApi, opUnwrap } from "../../client";
import { useChange } from "../../stepUp";
import { KEYS, useAssets } from "./api";
import { formatBytes, imageSnippet } from "./model";

type Asset = Schemas["SiteAssetOut"];
const ACCEPT = "image/png,image/jpeg,image/webp";
const MAX_BYTES = 1_500_000;

/** A library picture, fetched with the operator's sign-in (an <img> cannot send it) and shown as a thumbnail. */
function Thumb({ asset }: { asset: Asset }) {
  const picture = useQuery({
    queryKey: ["operator", "site", "asset-file", asset.id, asset.hash],
    staleTime: Infinity,
    queryFn: async () => {
      const { data, response } = await opApi.GET("/api/v1/operator/site/assets/{asset_id}/file", { params: { path: { asset_id: asset.id } }, parseAs: "blob" });
      if (!response.ok || !data) throw new Error("not loaded");
      return URL.createObjectURL(data as Blob);
    },
  });
  if (picture.isPending) return <Skeleton className="h-28 w-full" />;
  if (picture.isError) return <div className="flex h-28 items-center justify-center rounded-lg bg-sunken text-xs text-muted">?</div>;
  return <img src={picture.data} alt={asset.alt} width={asset.width} height={asset.height} className="h-28 w-full rounded-lg bg-sunken object-contain" />;
}

/** The picture library: upload (checked and cleaned by the server), describe, copy the Markdown line, remove. */
export default function MediaTab() {
  const { t } = useTranslation("operator");
  const queryClient = useQueryClient();
  const assets = useAssets();
  const input = useRef<HTMLInputElement>(null);
  const [alt, setAlt] = useState("");
  const [tooBig, setTooBig] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Asset | null>(null);
  const [editing, setEditing] = useState<{ asset: Asset; alt: string } | null>(null);

  const upload = useChange(
    (file: File) => opUnwrap(opApi.POST("/api/v1/operator/site/assets", {
      params: { query: { name: file.name, alt } },
      body: file as never,
      bodySerializer: (b: unknown) => b as BodyInit,
      headers: { "Content-Type": file.type },
    })),
    {
      onSuccess: () => { toast(t("website.media.uploaded"), "ok"); setAlt(""); void queryClient.invalidateQueries({ queryKey: KEYS.assets }); },
      onError: (e) => toast(e.message, "bad"),
    },
  );
  const describe = useChange(
    (v: { id: string; alt: string }) => opUnwrap(opApi.PUT("/api/v1/operator/site/assets/{asset_id}", { params: { path: { asset_id: v.id } }, body: { alt: v.alt } })),
    { onSuccess: () => { setEditing(null); void queryClient.invalidateQueries({ queryKey: KEYS.assets }); }, onError: (e) => toast(e.message, "bad") },
  );
  const remove = useChange(
    (id: string) => opUnwrap(opApi.DELETE("/api/v1/operator/site/assets/{asset_id}", { params: { path: { asset_id: id } } })),
    {
      onSuccess: () => { setRemoving(null); toast(t("website.media.removed"), "ok"); void queryClient.invalidateQueries({ queryKey: KEYS.assets }); },
      onError: (e) => { setRemoving(null); toast(e.message, "bad"); },
    },
  );

  function choose(file: File | undefined) {
    setTooBig(null);
    if (!file) return;
    if (file.size > MAX_BYTES) { setTooBig(t("website.media.tooBig", { size: formatBytes(MAX_BYTES) })); return; }
    upload.mutate(file);
    if (input.current) input.current.value = "";
  }

  return (
    <>
      <Alert tone="info" className="mb-4">{t("website.media.note")}</Alert>
      <Card title={t("website.media.add")}>
        <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <Field label={t("website.media.alt")} hint={t("website.media.altHint")}><Input value={alt} maxLength={300} onChange={(e) => setAlt(e.target.value)} /></Field>
          <div>
            <input ref={input} type="file" accept={ACCEPT} className="sr-only" aria-label={t("website.media.choose")} onChange={(e) => choose(e.target.files?.[0])} />
            <Button loading={upload.isPending} onClick={() => input.current?.click()}>{t("website.media.choose")}</Button>
          </div>
        </div>
        {tooBig && <p role="alert" className="mt-2 text-sm text-bad">{tooBig}</p>}
      </Card>
      <div className="mt-4">
        {assets.isPending ? <div className="grid gap-3 sm:grid-cols-3"><Skeleton className="h-48" /><Skeleton className="h-48" /><Skeleton className="h-48" /></div>
          : assets.isError ? <ErrorState message={assets.error.message} onRetry={() => void assets.refetch()} />
          : assets.data.length === 0 ? <EmptyState title={t("website.media.empty")} hint={t("website.media.emptyHint")} />
          : (
            <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {assets.data.map((a) => (
                <li key={a.id} className="space-y-2 rounded-xl border border-line bg-surface p-3">
                  <Thumb asset={a} />
                  <div>
                    <p className="truncate text-sm font-medium">{a.name}</p>
                    <p className="text-xs text-muted">{a.width} x {a.height} - {formatBytes(a.size_bytes)} <Badge>{a.content_type.replace("image/", "")}</Badge></p>
                    <p className="mt-1 text-xs text-muted">{a.alt || <em>{t("website.media.noAlt")}</em>}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="secondary" onClick={() => { void navigator.clipboard?.writeText(imageSnippet(a.asset_id, a.alt || a.name)); toast(t("website.media.copied"), "ok"); }}>{t("website.media.copy")}</Button>
                    <Button size="sm" variant="secondary" onClick={() => setEditing({ asset: a, alt: a.alt })}>{t("website.media.describe")}</Button>
                    <Button size="sm" variant="ghost" onClick={() => setRemoving(a)}>{t("website.media.remove")}</Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
      </div>
      <ConfirmDialog open={!!removing} onClose={() => setRemoving(null)} busy={remove.isPending} danger title={t("website.media.removeTitle")}
        message={t("website.media.removeMessage", { name: removing?.name })} confirmLabel={t("website.media.remove")} onConfirm={() => removing && remove.mutate(removing.id)} />
      {editing && (
        <ConfirmDialog open onClose={() => setEditing(null)} busy={describe.isPending} title={t("website.media.describe")} confirmLabel={t("website.save")}
          message={<Field label={t("website.media.alt")}><Input value={editing.alt} maxLength={300} onChange={(e) => setEditing({ ...editing, alt: e.target.value })} /></Field>}
          onConfirm={() => describe.mutate({ id: editing.asset.id, alt: editing.alt })} />
      )}
    </>
  );
}
