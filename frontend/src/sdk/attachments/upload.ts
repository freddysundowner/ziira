/** Sending one file with progress (fetch cannot report upload progress, so this uses XMLHttpRequest). */
import { ApiError, currentAccessToken, errorMessage, refreshTokens } from "../api";
import { type AttachedFile, encodeHeader, fitWithin, SHRINK_ABOVE_BYTES, SHRINK_LONG_SIDE } from "./logic";

export interface UploadRequest {
  entityType: string;
  entityId: string;
  file: Blob;
  name: string;
  category: string;
  visibility: "staff" | "shareable";
  caption: string;
  consent: string;
  key: string;
}

/** A big photo is shrunk to a sensible size first (less to send on mobile data; the picture's position is left behind too). */
export async function shrinkIfLarge(file: File): Promise<Blob> {
  if (!file.type.startsWith("image/") || file.type === "image/gif" || file.size <= SHRINK_ABOVE_BYTES || typeof createImageBitmap !== "function") return file;
  try {
    const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
    const { width, height } = fitWithin(bitmap.width, bitmap.height, SHRINK_LONG_SIDE);
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    canvas.getContext("2d")?.drawImage(bitmap, 0, 0, width, height);
    bitmap.close?.();
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.86));
    return blob && blob.size < file.size ? blob : file;
  } catch {
    return file;
  }
}

function send(request: UploadRequest, onProgress: (fraction: number) => void, signal: AbortSignal | undefined, token: string | null): Promise<{ status: number; body: unknown }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const query = new URLSearchParams({ entity_type: request.entityType, entity_id: request.entityId, category: request.category, visibility: request.visibility });
    xhr.open("POST", `/api/v1/files?${query.toString()}`);
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.setRequestHeader("Idempotency-Key", request.key);
    xhr.setRequestHeader("X-File-Name", encodeHeader(request.name));
    if (request.caption.trim()) xhr.setRequestHeader("X-File-Caption", encodeHeader(request.caption));
    if (request.consent.trim()) xhr.setRequestHeader("X-File-Consent", encodeHeader(request.consent));
    xhr.setRequestHeader("Content-Type", request.file.type || "application/octet-stream");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let body: unknown = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      resolve({ status: xhr.status, body });
    };
    xhr.onerror = () => resolve({ status: 0, body: null });
    xhr.ontimeout = () => resolve({ status: 0, body: null });
    xhr.onabort = () => reject(new DOMException("Cancelled", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(request.file);
  });
}

/** Upload one file; resolves with the stored file or throws an ApiError (status 0: no connection). A 401 refreshes the session once. */
export async function uploadFile(request: UploadRequest, onProgress: (fraction: number) => void = () => undefined, signal?: AbortSignal): Promise<AttachedFile> {
  let result = await send(request, onProgress, signal, currentAccessToken());
  if (result.status === 401 && (await refreshTokens()) === "ok") result = await send(request, onProgress, signal, currentAccessToken());
  if (result.status >= 200 && result.status < 300) return result.body as AttachedFile;
  throw new ApiError(result.status === 0 ? "Cannot reach the server. Check your connection and try again." : errorMessage(result.body, result.status), result.status);
}
