import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../api";
import { type AttachedFile, isRetryable, newUploadKey, retryDelaySeconds } from "./logic";
import { shrinkIfLarge, uploadFile } from "./upload";

export interface PendingUpload {
  id: string;
  key: string;
  name: string;
  file: Blob;
  preview: string | null;
  category: string;
  visibility: "staff" | "shareable";
  caption: string;
  consent: string;
  progress: number;
  /** sending: on its way; waiting: failed for a reason that may pass (no signal), will try again; failed: needs a person. */
  status: "sending" | "waiting" | "failed";
  error: string | null;
  attempt: number;
}

export interface UploadChoice { category: string; visibility: "staff" | "shareable"; caption: string; consent: string }

/**
 * The uploads of one record that are not stored yet. Photos are sent two at a time; one that fails because the connection is
 * gone (or the server is busy) waits and is tried again by itself, and at once when the browser comes back online. Each upload has
 * a client-made key, so a try that did arrive but whose answer was lost is never stored twice.
 */
export function useUploads(entityType: string, entityId: string, onStored: (file: AttachedFile) => void) {
  const [items, setItems] = useState<PendingUpload[]>([]);
  const running = useRef(new Set<string>());
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const itemsRef = useRef<PendingUpload[]>([]);
  itemsRef.current = items;
  const stored = useRef(onStored);
  stored.current = onStored;

  const patch = useCallback((id: string, change: Partial<PendingUpload>) => setItems((all) => all.map((i) => (i.id === id ? { ...i, ...change } : i))), []);
  const drop = useCallback((id: string) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setItems((all) => {
      const gone = all.find((i) => i.id === id);
      if (gone?.preview && typeof URL.revokeObjectURL === "function") URL.revokeObjectURL(gone.preview);
      return all.filter((i) => i.id !== id);
    });
  }, []);

  const start = useCallback(async (item: PendingUpload) => {
    if (running.current.has(item.id)) return;
    running.current.add(item.id);
    clearTimeout(timers.current.get(item.id));
    patch(item.id, { status: "sending", progress: 0, error: null });
    try {
      const result = await uploadFile({ entityType, entityId, file: item.file, name: item.name, category: item.category, visibility: item.visibility, caption: item.caption, consent: item.consent, key: item.key },
        (progress) => patch(item.id, { progress }));
      stored.current(result);
      drop(item.id);
    } catch (e) {
      const status = e instanceof ApiError ? e.status : 0;
      const message = e instanceof Error ? e.message : "";
      const attempt = item.attempt + 1;
      if (isRetryable(status)) {
        patch(item.id, { status: "waiting", error: message, attempt, progress: 0 });
        timers.current.set(item.id, setTimeout(() => { const now = itemsRef.current.find((i) => i.id === item.id); if (now) void start({ ...now, attempt }); }, retryDelaySeconds(attempt) * 1000));
      } else {
        patch(item.id, { status: "failed", error: message, attempt, progress: 0 });
      }
    } finally {
      running.current.delete(item.id);
    }
  }, [entityType, entityId, patch, drop]);

  const add = useCallback(async (files: File[], choice: UploadChoice) => {
    for (const file of files) {
      const blob = await shrinkIfLarge(file);
      const item: PendingUpload = {
        id: newUploadKey(), key: newUploadKey(), name: file.name || "photo.jpg", file: blob, preview: blob.type.startsWith("image/") && typeof URL.createObjectURL === "function" ? URL.createObjectURL(blob) : null,
        ...choice, progress: 0, status: "sending", error: null, attempt: 0,
      };
      setItems((all) => [...all, item]);
      void start(item);
    }
  }, [start]);

  const retry = useCallback((id: string) => { const item = itemsRef.current.find((i) => i.id === id); if (item) void start(item); }, [start]);

  useEffect(() => {
    const online = () => itemsRef.current.filter((i) => i.status === "waiting").forEach((i) => void start(i));
    window.addEventListener("online", online);
    return () => window.removeEventListener("online", online);
  }, [start]);

  useEffect(() => {
    if (items.length === 0) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [items.length]);

  useEffect(() => () => { timers.current.forEach(clearTimeout); }, []);

  return { items, add, retry, remove: drop };
}
