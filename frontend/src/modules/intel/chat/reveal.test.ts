import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { endsSentence, nextStop, SENTENCE_MS, showAtOnce, useReveal, WORD_MS } from "./reveal";

const motion = (reduce: boolean) =>
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: reduce && query.includes("reduce"), addEventListener() {}, removeEventListener() {} }));

beforeEach(() => { vi.useFakeTimers(); motion(false); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("nextStop and endsSentence", () => {
  it("moves one word at a time, keeping the space after it", () => {
    const text = "Sales were 1,250.00 today.";
    expect(text.slice(0, nextStop(text, 0))).toBe("Sales ");
    expect(text.slice(0, nextStop(text, 6))).toBe("Sales were ");
    expect(nextStop(text, text.length)).toBe(text.length);
    expect(nextStop("a\n\nb", 1)).toBe(4);
  });
  it("knows where a sentence ends but not a decimal", () => {
    expect(endsSentence("today. ")).toBe(true);
    expect(endsSentence("1,250.00 ")).toBe(false);
    expect(endsSentence("What?")).toBe(true);
  });
});

describe("useReveal", () => {
  it("types the text out word by word, with a longer pause after a sentence", () => {
    const { result } = renderHook(() => useReveal("One two. Three", true));
    expect(result.current.shown).toBe("");
    act(() => { vi.advanceTimersByTime(WORD_MS); });
    expect(result.current.shown).toBe("One ");
    act(() => { vi.advanceTimersByTime(WORD_MS); });
    expect(result.current.shown).toBe("One two. ");
    act(() => { vi.advanceTimersByTime(WORD_MS); });
    expect(result.current.shown).toBe("One two. ");                      // it breathes after the full stop
    act(() => { vi.advanceTimersByTime(SENTENCE_MS - WORD_MS); });
    expect(result.current.shown).toBe("One two. Three");
    expect(result.current.typing).toBe(false);
  });
  it("keeps up as more text arrives", () => {
    const { result, rerender } = renderHook(({ text }) => useReveal(text, true), { initialProps: { text: "One " } });
    act(() => { vi.advanceTimersByTime(WORD_MS); });
    rerender({ text: "One two three" });
    for (let i = 0; i < 3; i++) act(() => { vi.advanceTimersByTime(WORD_MS); });
    expect(result.current.shown).toBe("One two three");
  });
  it("shows everything at once when clicked, and for text that arrives later", () => {
    const { result, rerender } = renderHook(({ text }) => useReveal(text, true), { initialProps: { text: "One two three" } });
    act(() => result.current.skip());
    expect(result.current.shown).toBe("One two three");
    rerender({ text: "One two three four" });
    expect(result.current.shown).toBe("One two three four");
  });
  it("shows everything at once when not animating, when motion is reduced, and when the tab is hidden", () => {
    expect(renderHook(() => useReveal("All of it", false)).result.current.shown).toBe("All of it");
    motion(true);
    expect(showAtOnce()).toBe(true);
    const reduced = renderHook(() => useReveal("All of it", true));
    act(() => { vi.advanceTimersByTime(1); });
    expect(reduced.result.current.shown).toBe("All of it");
    motion(false);
    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    const hidden = renderHook(() => useReveal("All of it", true));
    act(() => { vi.advanceTimersByTime(1); });
    expect(hidden.result.current.shown).toBe("All of it");
  });
});
