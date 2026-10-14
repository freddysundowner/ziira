/**
 * A tiny bus so code outside React (the query cache, the API layer) can show a toast. <ToastProvider> subscribes.
 */
export type Tone = "ok" | "bad" | "info" | "warn";
export interface ToastMessage {
  id: number;
  tone: Tone;
  text: string;
}

type Listener = (toast: ToastMessage) => void;
let listener: Listener | null = null;
let counter = 0;

export function onToast(callback: Listener | null): void {
  listener = callback;
}

export function toast(text: string, tone: Tone = "info"): void {
  listener?.({ id: ++counter, tone, text });
}
