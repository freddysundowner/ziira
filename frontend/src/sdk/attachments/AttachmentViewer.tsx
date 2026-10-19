import { ChevronLeft, ChevronRight, Download, ExternalLink, FileText, Lock, Share2, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { api, errorMessage, unwrap } from "../api";
import { useTranslation } from "../i18n";
import { Alert, Button, Field, IconButton, Input, Modal, Select, Switch, Textarea } from "../ui";
import { type AttachedFile, formatBytes } from "./logic";

interface Props {
  files: readonly AttachedFile[];
  index: number;
  categories: readonly { key: string; label: string }[];
  canEdit: boolean;
  photoConsent: boolean;
  onIndex: (index: number) => void;
  onClose: () => void;
  onChange: (changes: { caption?: string; category?: string; visibility?: "staff" | "shareable"; consent_note?: string }) => Promise<void>;
  onDelete: (reason: string) => Promise<void>;
}

/** Open a signed address for one form of a file in a new tab (a PDF to read, or the full-size original to save). */
async function openLink(id: string, variant: "original" | "web", download: boolean) {
  const link = await unwrap(api.POST("/api/v1/files/{file_id}/link", { params: { path: { file_id: id } }, body: { variant, seconds: 120 } }));
  window.open(`${link.path}${download ? "?download=true" : ""}`, "_blank", "noopener");
}

/** One file, large: the picture or a PDF card, its details, and (for people who may edit) the caption, kind, visibility and delete. */
export function AttachmentViewer({ files, index, categories, canEdit, photoConsent, onIndex, onClose, onChange, onDelete }: Props) {
  const { t } = useTranslation();
  const file = files[index];
  const [caption, setCaption] = useState(file?.caption ?? "");
  const [consent, setConsent] = useState(file?.consent_note ?? "");
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");

  useEffect(() => { setCaption(file?.caption ?? ""); setConsent(file?.consent_note ?? ""); setFailure(null); }, [file?.id, file?.caption, file?.consent_note]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement | null)?.closest("input,textarea,select")) return;
      if (e.key === "ArrowLeft" && index > 0) onIndex(index - 1);
      if (e.key === "ArrowRight" && index < files.length - 1) onIndex(index + 1);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [index, files.length, onIndex]);
  useEffect(() => { if (!file) onClose(); }, [file, onClose]);
  if (!file) return null;

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setFailure(null);
    try { await action(); } catch (e) { setFailure(errorMessage(e)); } finally { setBusy(false); }
  };
  const kinds = categories.some((c) => c.key === file.category) ? categories : [...categories, { key: file.category, label: file.category }];

  return (
    <>
      <Modal open onClose={onClose} title={file.name} size="lg"
        footer={<>
          {canEdit && <Button variant="ghost" className="mr-auto text-bad" onClick={() => { setReason(""); setAsking(true); }}><Trash2 className="h-4 w-4" />{t("files.delete")}</Button>}
          <Button variant="secondary" onClick={() => void run(() => openLink(file.id, "original", true))}><Download className="h-4 w-4" />{t("files.download")}</Button>
          <Button variant="secondary" onClick={onClose}>{t("files.close")}</Button>
        </>}>
        <div className="space-y-4">
          <div className="relative flex min-h-[200px] items-center justify-center rounded-xl bg-sunken">
            {file.kind === "image" && file.web_url ? (
              <img src={file.web_url} alt={file.caption || file.name} className="max-h-[56vh] w-auto max-w-full rounded-xl object-contain" />
            ) : (
              <div className="flex flex-col items-center gap-3 p-8 text-center">
                <FileText className="h-12 w-12 text-muted" />
                <div className="text-sm text-muted">{file.page_count ? t("files.pdfPages", { count: file.page_count }) : t("files.pdf")}</div>
                <Button variant="secondary" onClick={() => void run(() => openLink(file.id, "original", false))}><ExternalLink className="h-4 w-4" />{t("files.openPdf")}</Button>
              </div>
            )}
            {files.length > 1 && (
              <>
                <IconButton label={t("files.previous")} disabled={index === 0} onClick={() => onIndex(index - 1)} className="absolute left-2 top-1/2 -translate-y-1/2 bg-surface/80"><ChevronLeft className="h-5 w-5" /></IconButton>
                <IconButton label={t("files.next")} disabled={index === files.length - 1} onClick={() => onIndex(index + 1)} className="absolute right-2 top-1/2 -translate-y-1/2 bg-surface/80"><ChevronRight className="h-5 w-5" /></IconButton>
              </>
            )}
          </div>
          <p className="text-xs text-muted">
            {t("files.addedBy", { who: file.created_by_name ?? t("files.someone"), when: new Date(file.created_at).toLocaleString() })} · {formatBytes(file.size_bytes)}
            {file.width && file.height ? ` · ${file.width}×${file.height}` : ""}{file.location_stripped ? ` · ${t("files.locationRemoved")}` : ""}
          </p>
          {failure && <Alert tone="bad">{failure}</Alert>}
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t("files.caption")} className="sm:col-span-2">
              <Input value={caption} maxLength={300} disabled={!canEdit || busy} placeholder={canEdit ? t("files.captionPlaceholder") : ""}
                onChange={(e) => setCaption(e.target.value)} onBlur={() => { if (caption.trim() !== file.caption) void run(() => onChange({ caption })); }} />
            </Field>
            <Field label={t("files.kind")}>
              <Select value={file.category} disabled={!canEdit || busy} onChange={(e) => void run(() => onChange({ category: e.target.value }))}>
                {kinds.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
              </Select>
            </Field>
            <div className="space-y-1.5">
              <div className="text-sm font-medium">{t("files.visibility")}</div>
              <div className="flex items-center gap-2 text-sm">
                <Switch checked={file.visibility === "shareable"} disabled={!canEdit || busy} label={t("files.shareable")}
                  onChange={(on) => void run(() => onChange({ visibility: on ? "shareable" : "staff" }))} />
                {file.visibility === "shareable" ? <><Share2 className="h-4 w-4 text-info" />{t("files.shareable")}</> : <><Lock className="h-4 w-4 text-muted" />{t("files.staffOnly")}</>}
              </div>
              <p className="text-xs text-muted">{file.visibility === "shareable" ? t("files.shareableHint") : t("files.staffOnlyHint")}</p>
            </div>
            {photoConsent && (
              <Field label={t("files.consent")} hint={t("files.consentHint")} className="sm:col-span-2">
                <Input value={consent} maxLength={300} disabled={!canEdit || busy} onChange={(e) => setConsent(e.target.value)}
                  onBlur={() => { if (consent.trim() !== file.consent_note) void run(() => onChange({ consent_note: consent })); }} />
              </Field>
            )}
          </div>
        </div>
      </Modal>
      <Modal open={asking} onClose={() => setAsking(false)} title={t("files.deleteTitle")} size="sm"
        footer={<>
          <Button variant="secondary" onClick={() => setAsking(false)}>{t("files.cancel")}</Button>
          <Button variant="danger" loading={busy} disabled={reason.trim().length < 3} onClick={() => void run(async () => { await onDelete(reason.trim()); setAsking(false); })}>{t("files.delete")}</Button>
        </>}>
        <p className="mb-3 text-sm text-muted">{t("files.deleteMessage")}</p>
        <Field label={t("files.reason")}>
          <Textarea value={reason} maxLength={300} data-autofocus onChange={(e) => setReason(e.target.value)} />
        </Field>
      </Modal>
    </>
  );
}
