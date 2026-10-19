import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { type AskRequest, type StreamEvent } from "./sse";
import { useAskChat } from "./useAskChat";

const ev = (event: string, data: Record<string, unknown> = {}): StreamEvent => ({ event, data });

/** A scripted stream: yields the events, optionally waiting for `gate` between them; ends early when aborted. */
function scripted(events: StreamEvent[], gate?: Promise<void>) {
  const requests: AskRequest[] = [];
  const stream = async function* (request: AskRequest, signal?: AbortSignal) {
    requests.push(request);
    for (const [i, e] of events.entries()) {
      if (gate && i === 1) await gate;
      if (signal?.aborted) return;
      yield e;
    }
  };
  return { stream, requests };
}

beforeEach(() => sessionStorage.clear());

describe("useAskChat", () => {
  it("shows your line at once, then Ziira's: waiting with what it does, then the text, then done with the evidence", async () => {
    let release!: () => void;
    const gate = new Promise<void>((r) => { release = r; });
    const { stream, requests } = scripted([ev("status", { text: "Looking at your sales" }), ev("text", { text: "Sales were 116.00. " }), ev("text", { text: "Good." }),
      ev("sources", { sources: [{ tool: "pos_sales_summary", params: {}, rows: [], summary: {} }] }), ev("done", { session_id: "s1", flagged: false, capped: null })], gate);
    const { result } = renderHook(() => useAskChat({ companyId: "c1", language: "en", stream }));
    act(() => { result.current.send("  How were sales?  "); });
    expect(result.current.messages.map((m) => [m.role, m.text, m.state])).toEqual([["user", "How were sales?", "done"], ["ziira", "", "waiting"]]);
    expect(result.current.busy).toBe(true);
    await waitFor(() => expect(result.current.messages[1]?.status).toBe("Looking at your sales"));
    expect(result.current.send("again")).toBe(false);                      // one question at a time
    release();
    await waitFor(() => expect(result.current.messages[1]?.state).toBe("done"));
    const answer = result.current.messages[1]!;
    expect(answer.text).toBe("Sales were 116.00. Good.");
    expect(answer.status).toBeUndefined();
    expect(answer.sources).toHaveLength(1);
    expect(requests[0]).toEqual({ question: "How were sales?", company_id: "c1", session_id: undefined, language: "en" });
    expect(result.current.busy).toBe(false);
  });

  it("sends the conversation id with the next question so a follow-up has its context", async () => {
    const { stream, requests } = scripted([ev("text", { text: "A. " }), ev("done", { session_id: "s9" })]);
    const { result } = renderHook(() => useAskChat({ companyId: "c1", language: "sw", stream }));
    act(() => { result.current.send("one"); });
    await waitFor(() => expect(result.current.busy).toBe(false));
    act(() => { result.current.send("and last week?"); });
    await waitFor(() => expect(requests).toHaveLength(2));
    expect(requests[1]).toMatchObject({ session_id: "s9", language: "sw" });
  });

  it("stop keeps what was written and marks it stopped; nothing more arrives", async () => {
    const { stream } = scripted([ev("text", { text: "First. " }), ev("text", { text: "Second. " })], new Promise(() => undefined));
    const { result } = renderHook(() => useAskChat({ companyId: "c1", language: "en", stream }));
    act(() => { result.current.send("q"); });
    await waitFor(() => expect(result.current.messages[1]?.text).toBe("First. "));
    act(() => result.current.stop());
    expect(result.current.messages[1]).toMatchObject({ state: "stopped", text: "First. " });
    expect(result.current.busy).toBe(false);
  });

  it("an error event shows its plain words, calls onRefused, and retry asks again in its place", async () => {
    let refused = 0;
    const failing = scripted([ev("error", { reason: "provider_failed", message: "I could not reach the assistant." })]);
    const { result, rerender } = renderHook(({ stream }) => useAskChat({ companyId: "c1", language: "en", stream, onRefused: () => { refused += 1; } }),
      { initialProps: { stream: failing.stream } });
    act(() => { result.current.send("q"); });
    await waitFor(() => expect(result.current.messages[1]?.state).toBe("error"));
    expect(result.current.messages[1]).toMatchObject({ error: "I could not reach the assistant.", reason: "provider_failed", question: "q" });
    expect(refused).toBe(1);
    const working = scripted([ev("text", { text: "Fine. " }), ev("done", { session_id: "s" })]);
    rerender({ stream: working.stream });
    act(() => result.current.retry(result.current.messages[1]!.id));
    await waitFor(() => expect(result.current.messages.at(-1)?.state).toBe("done"));
    expect(result.current.messages.map((m) => m.role)).toEqual(["user", "ziira"]);   // the failed pair was replaced, not repeated
    expect(result.current.messages[1]?.text).toBe("Fine. ");
  });

  it("a stream that ends without finishing, or breaks, is an error the person can retry", async () => {
    const cut = scripted([ev("text", { text: "Half" })]);
    const { result } = renderHook(() => useAskChat({ companyId: "c1", language: "en", stream: cut.stream }));
    act(() => { result.current.send("q"); });
    await waitFor(() => expect(result.current.messages[1]?.state).toBe("error"));
    expect(result.current.messages[1]).toMatchObject({ reason: "connection", text: "Half" });
    // eslint-disable-next-line require-yield
    const broken = async function* (): AsyncGenerator<StreamEvent> { throw new Error("network"); };
    const second = renderHook(() => useAskChat({ companyId: "c1", language: "en", stream: broken }));
    sessionStorage.clear();
    act(() => { second.result.current.send("q"); });
    await waitFor(() => expect(second.result.current.messages.at(-1)?.reason).toBe("connection"));
  });

  it("keeps the conversation for this browser session and shows it again without typing it out", async () => {
    const { stream } = scripted([ev("text", { text: "Kept. " }), ev("done", { session_id: "s5" })]);
    const first = renderHook(() => useAskChat({ companyId: "c1", language: "en", stream }));
    act(() => { first.result.current.send("q"); });
    await waitFor(() => expect(first.result.current.busy).toBe(false));
    first.unmount();
    const again = renderHook(() => useAskChat({ companyId: "c1", language: "en", stream }));
    expect(again.result.current.messages.map((m) => m.text)).toEqual(["q", "Kept. "]);
    expect(again.result.current.messages[1]?.fresh).toBe(false);
    act(() => again.result.current.reset());
    expect(again.result.current.messages).toEqual([]);
  });
});
