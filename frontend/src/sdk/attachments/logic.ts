/** Pure helpers of the Attachments component: what may be chosen, how files are grouped, and how an upload is retried. */
import type { Schemas } from "../api";

export type AttachedFile = Schemas["AttachedFileOut"];
export type FileConfig = Schemas["AttachedFileConfigOut"];

export type FileProblem = "type" | "tooBig" | "empty" | "heic" | "full";

const TYPES = new Set(["image/jpeg", "image/png", "image/webp", "application/pdf"]);
const EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp", "pdf"]);

const extensionOf = (name: string) => (name.includes(".") ? name.split(".").pop()!.toLowerCase() : "");

/** Whether a chosen file can be tried. The server reads the real type from the bytes; this only saves a pointless upload. */
export function checkChoice(file: { name: string; type: string; size: number }, config: Pick<FileConfig, "max_file_bytes">, held: number, maxPerRecord: number): FileProblem | null {
  if (held >= maxPerRecord) return "full";
  if (file.size === 0) return "empty";
  const ext = extensionOf(file.name);
  if (file.type === "image/heic" || file.type === "image/heif" || ext === "heic" || ext === "heif") return "heic";
  if (!TYPES.has(file.type) && !(file.type === "" && EXTENSIONS.has(ext))) return "type";
  if (file.size > config.max_file_bytes) return "tooBig";
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export interface Group { key: string; label: string; files: AttachedFile[] }

/** Files grouped by kind of photo, kinds in the order the record's unit gave them, then any other kind a file carries. */
export function groupByCategory(files: readonly AttachedFile[], categories: readonly { key: string; label: string }[]): Group[] {
  const groups = new Map<string, Group>(categories.map((c) => [c.key, { key: c.key, label: c.label, files: [] }]));
  for (const f of files) {
    const group = groups.get(f.category) ?? { key: f.category, label: f.category.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase()), files: [] };
    group.files.push(f);
    groups.set(f.category, group);
  }
  return [...groups.values()].filter((g) => g.files.length > 0);
}

/** Header values may hold any text: they travel percent-encoded as UTF-8 (and never in the URL). */
export const encodeHeader = (text: string): string => encodeURIComponent(text.trim());

/** A client-made id that makes a retry of the same upload safe. */
export function newUploadKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`;
}

/** Only photos bigger than this are shrunk before sending (a phone photo is often 5 to 8 MB). */
export const SHRINK_ABOVE_BYTES = 2_500_000;
export const SHRINK_LONG_SIDE = 2560;

export function fitWithin(width: number, height: number, longSide: number): { width: number; height: number } {
  const scale = Math.min(1, longSide / Math.max(width, height));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

/** Whether a failed upload is worth trying again by itself (no signal, a busy server) rather than needing a person. */
export function isRetryable(status: number): boolean {
  return status === 0 || status === 408 || status === 425 || status === 429 || status >= 500;
}

/** Seconds to wait before the next automatic try: 5, 10, 20, 40 ... at most 5 minutes. */
export function retryDelaySeconds(attempt: number): number {
  return Math.min(300, 5 * 2 ** Math.max(0, attempt - 1));
}
