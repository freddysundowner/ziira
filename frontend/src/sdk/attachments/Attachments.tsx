import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, FileText, Lock, Paperclip, RefreshCw, Share2, X } from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { api, ApiError, errorMessage, unwrap } from "../api";
import { useTranslation } from "../i18n";
import { toast } from "../notify";
import { Alert, Badge, Button, Card, EmptyState, ErrorState, Field, Input, Select, Skeleton } from "../ui";
import { AttachmentViewer } from "./AttachmentViewer";
import { type AttachedFile, checkChoice, formatBytes, groupByCategory } from "./logic";
import { type PendingUpload, useUploads } from "./useUploads";

const FOUR_MINUTES = 4 * 60 * 1000;

/**
 * The photos and files of one record: take a photo (a phone opens its camera) or choose files, a grid by kind of photo with
 * captions and a staff-only/shareable mark, a viewer, delete with a reason, and upload progress with retry. A failed upload
 * (no signal) waits and tries again by itself. Shows nothing to someone who may not open the record.
 */
export function Attachments({ entityType, entityId, title }: { entityType: string; entityId: string; title?: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const listKey = ["attachments", entityType, entityId];
  const configKey = ["attachments-config", entityType, entityId];
  const camera = useRef<HTMLInputElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const [category, setCategory] = useState("");
  const [consent, setConsent] = useState("");
  const [problems, setProblems] = useState<string[]>([]);
  const [open, setOpen] = useState<number | null>(null);

  const config = useQuery({
    queryKey: configKey, retry: false,
    queryFn: () => unwrap(api.GET("/api/v1/files/config", { params: { query: { entity_type: entityType, entity_id: entityId } } })),
  });
  const list = useQuery({
    queryKey: listKey, retry: false, enabled: config.isSuccess,
    refetchInterval: FOUR_MINUTES, refetchOnWindowFocus: true,        // the picture addresses are short-lived: ask for fresh ones
    queryFn: () => unwrap(api.GET("/api/v1/files", { params: { query: { entity_type: entityType, entity_id: entityId } } })),
  });
  const stored = useCallback(() => { void qc.invalidateQueries({ queryKey: listKey }); void qc.invalidateQueries({ queryKey: configKey }); }, [qc]);   // eslint-disable-line react-hooks/exhaustive-deps
  const uploads = useUploads(entityType, entityId, stored);

  const patch = useMutation({
    meta: { silent: true },
    mutationFn: ({ id, changes }: { id: string; changes: { caption?: string; category?: string; visibility?: "staff" | "shareable"; consent_note?: string } }) =>
      unwrap(api.PATCH("/api/v1/files/{file_id}", { params: { path: { file_id: id } }, body: changes })),
    onSuccess: (saved) => { qc.setQueryData<AttachedFile[]>(listKey, (all) => all?.map((f) => (f.id === saved.id ? saved : f))); },
  });
  const remove = useMutation({
    meta: { silent: true },
    mutationFn: ({ id, reason }: { id: string; reason: string }) => unwrap(api.POST("/api/v1/files/{file_id}/delete", { params: { path: { file_id: id } }, body: { reason } })),
    onSuccess: () => { toast(t("files.deleted"), "ok"); stored(); },
  });

  if (config.isLoading) return <Skeleton className="h-32 rounded-xl" />;
  if (config.error instanceof ApiError && (config.error.status === 403 || config.error.status === 404)) return null;
  if (config.error || !config.data) return <ErrorState title={t("files.loadFailed")} message={errorMessage(config.error)} onRetry={() => void config.refetch()} />;
  const settings = config.data;
  const files = list.data ?? [];
  const kinds = settings.categories;
  const chosenKind = category || kinds[0]?.key || "general";
  const groups = groupByCategory(files, kinds);
  const flat = groups.flatMap((g) => g.files);

  const choose = (chosen: FileList | null) => {
    if (!chosen || chosen.length === 0) return;
    const accepted: File[] = [];
    const refused: string[] = [];
    let held = files.length + uploads.items.length;
    for (const file of Array.from(chosen)) {
      const problem = checkChoice(file, settings, held, settings.max_per_record);
      if (problem) refused.push(t(`files.problem.${problem}`, { name: file.name || t("files.thisFile"), size: formatBytes(settings.max_file_bytes), count: settings.max_per_record }));
      else { accepted.push(file); held += 1; }
    }
    setProblems(refused);
    if (accepted.length) void uploads.add(accepted, { category: chosenKind, visibility: "staff", caption: "", consent });
    if (camera.current) camera.current.value = "";
    if (picker.current) picker.current.value = "";
  };

  return (
    <Card title={title ?? t("files.title")} actions={files.length > 0 ? <Badge>{files.length}</Badge> : undefined}>
      {settings.can_add && (
        <div className="mb-4 space-y-3">
          <div className="flex flex-wrap items-end gap-2">
            {kinds.length > 1 && (
              <Field label={t("files.kindOfPhoto")} className="min-w-[10rem]">
                <Select value={chosenKind} onChange={(e) => setCategory(e.target.value)}>{kinds.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}</Select>
              </Field>
            )}
            <Button onClick={() => camera.current?.click()}><Camera className="h-4 w-4" />{t("files.takePhoto")}</Button>
            <Button variant="secondary" onClick={() => picker.current?.click()}><Paperclip className="h-4 w-4" />{t("files.chooseFiles")}</Button>
            <input ref={camera} type="file" accept="image/*" capture="environment" className="hidden" data-testid="camera-input" onChange={(e) => choose(e.target.files)} />
            <input ref={picker} type="file" accept="image/jpeg,image/png,image/webp,application/pdf" multiple className="hidden" data-testid="file-input" onChange={(e) => choose(e.target.files)} />
          </div>
          {settings.photo_consent && (
            <Field label={t("files.consent")} hint={t("files.consentHint")}>
              <Input value={consent} maxLength={300} onChange={(e) => setConsent(e.target.value)} />
            </Field>
          )}
        </div>
      )}
      {problems.length > 0 && <Alert tone="warn" className="mb-3">{problems.map((p) => <div key={p}>{p}</div>)}</Alert>}

      {uploads.items.length > 0 && (
        <ul className="mb-4 grid grid-cols-1 gap-2 sm:grid-cols-2" aria-label={t("files.uploading")}>
          {uploads.items.map((u) => <PendingRow key={u.id} item={u} onRetry={() => uploads.retry(u.id)} onRemove={() => uploads.remove(u.id)} />)}
        </ul>
      )}

      {list.isLoading ? <Skeleton className="h-28 rounded-xl" />
        : list.error ? <ErrorState title={t("files.loadFailed")} message={errorMessage(list.error)} onRetry={() => void list.refetch()} />
        : flat.length === 0 && uploads.items.length === 0 ? (
          <EmptyState title={t("files.empty")} hint={settings.can_add ? t("files.emptyHint") : undefined} />
        ) : (
          <div className="space-y-5">
            {groups.map((g) => (
              <section key={g.key} aria-label={g.label}>
                {groups.length > 1 && <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">{g.label} <span className="font-normal">({g.files.length})</span></h3>}
                <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5">
                  {g.files.map((f) => <li key={f.id}><Tile file={f} onOpen={() => setOpen(flat.findIndex((x) => x.id === f.id))} /></li>)}
                </ul>
              </section>
            ))}
          </div>
        )}

      {open !== null && flat.length > 0 && (
        <AttachmentViewer files={flat} index={Math.min(open, flat.length - 1)} categories={kinds} canEdit={settings.can_add} photoConsent={settings.photo_consent}
          onIndex={setOpen} onClose={() => setOpen(null)}
          onChange={async (changes) => { await patch.mutateAsync({ id: flat[Math.min(open, flat.length - 1)]!.id, changes }); }}
          onDelete={async (reason) => { await remove.mutateAsync({ id: flat[Math.min(open, flat.length - 1)]!.id, reason }); }} />
      )}
    </Card>
  );
}

function Tile({ file, onOpen }: { file: AttachedFile; onOpen: () => void }) {
  const { t } = useTranslation();
  const label = file.caption || file.name;
  return (
    <button type="button" onClick={onOpen} aria-label={label} className="group relative block aspect-square w-full overflow-hidden rounded-lg border border-line bg-sunken text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">
      {file.thumb_url ? <img src={file.thumb_url} alt={label} loading="lazy" className="h-full w-full object-cover" />
        : <span className="flex h-full w-full flex-col items-center justify-center gap-1 p-2 text-center text-xs text-muted"><FileText className="h-8 w-8" /><span className="line-clamp-2 break-all">{file.name}</span></span>}
      <span className="absolute right-1 top-1 rounded-full bg-surface/90 p-1 text-muted shadow-card" title={file.visibility === "shareable" ? t("files.shareable") : t("files.staffOnly")}>
        {file.visibility === "shareable" ? <Share2 className="h-3 w-3 text-info" /> : <Lock className="h-3 w-3" />}
      </span>
      {file.caption && <span className="absolute inset-x-0 bottom-0 line-clamp-1 bg-black/55 px-1.5 py-0.5 text-[11px] text-white">{file.caption}</span>}
    </button>
  );
}

function PendingRow({ item, onRetry, onRemove }: { item: PendingUpload; onRetry: () => void; onRemove: () => void }) {
  const { t } = useTranslation();
  return (
    <li className="flex items-center gap-3 rounded-lg border border-line p-2">
      {item.preview ? <img src={item.preview} alt="" className="h-12 w-12 shrink-0 rounded object-cover" /> : <FileText className="h-12 w-12 shrink-0 text-muted" />}
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm">{item.name}</div>
        {item.status === "sending" && (
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-sunken" role="progressbar" aria-valuenow={Math.round(item.progress * 100)} aria-valuemin={0} aria-valuemax={100} aria-label={t("files.uploading")}>
            <div className="h-full bg-brand transition-all" style={{ width: `${Math.max(5, Math.round(item.progress * 100))}%` }} />
          </div>
        )}
        {item.status === "waiting" && <div className="text-xs text-warn">{t("files.waiting")}</div>}
        {item.status === "failed" && <div className="text-xs text-bad" role="alert">{item.error}</div>}
      </div>
      {item.status !== "sending" && <Button size="sm" variant="secondary" onClick={onRetry}><RefreshCw className="h-3.5 w-3.5" />{t("files.retry")}</Button>}
      {item.status !== "sending" && <button type="button" aria-label={t("files.discard")} title={t("files.discard")} onClick={onRemove} className="rounded p-1 text-muted hover:bg-sunken"><X className="h-4 w-4" /></button>}
    </li>
  );
}
