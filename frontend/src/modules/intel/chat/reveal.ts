import { useEffect, useState } from "react";

/** Milliseconds between words while an answer types out, and the extra pause after a sentence. */
export const WORD_MS = 28;
export const SENTENCE_MS = 160;

/** Where the next word of `text` ends when revealing from `from` (the word and the white space after it). */
export function nextStop(text: string, from: number): number {
  const word = /\s*\S+\s*/y;
  word.lastIndex = from;
  const found = word.exec(text);
  return found ? from + found[0].length : text.length;
}

/** True when the text so far ends a sentence (so the typing breathes before the next one). */
export function endsSentence(piece: string): boolean {
  return /[.!?]\s*$/.test(piece);
}

/** True when text should appear at once: the person asked for less motion, or the tab is hidden (timers there are slowed anyway). */
export function showAtOnce(): boolean {
  if (typeof document !== "undefined" && document.hidden) return true;
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * The part of `text` to show now. With `animate` it types out word by word (and keeps up as more text arrives); without, all of it at once.
 * `skip()` shows everything now and for any text that arrives later.
 */
export function useReveal(text: string, animate: boolean): { shown: string; typing: boolean; skip: () => void } {
  const [count, setCount] = useState(animate ? 0 : text.length);
  const [skipped, setSkipped] = useState(false);
  const instant = !animate || skipped;
  useEffect(() => {
    if (instant || showAtOnce()) { setCount(text.length); return; }
    if (count >= text.length) return;
    const stop = nextStop(text, count);
    const id = setTimeout(() => setCount(stop), endsSentence(text.slice(0, count)) ? SENTENCE_MS : WORD_MS);
    return () => clearTimeout(id);
  }, [text, count, instant]);
  const shownCount = instant ? text.length : Math.min(count, text.length);
  return { shown: text.slice(0, shownCount), typing: shownCount < text.length, skip: () => setSkipped(true) };
}
