import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { type ChatMessage } from "../chat/useAskChat";
import { TypingDots, UserBubble, ZiiraBubble } from "./ChatParts";

vi.mock("./AiBadge", () => ({ default: () => null }));
vi.mock("./AnswerSources", () => ({ default: () => <p>sources table</p> }));

const base: ChatMessage = { id: "z1", role: "ziira", text: "", state: "waiting", question: "q", fresh: true };
beforeEach(() => { vi.useFakeTimers(); vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} })); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("the chat bubbles", () => {
  it("shows the dots and the live status while waiting, and no answer yet", () => {
    render(<ZiiraBubble message={{ ...base, status: "Looking at your sales" }} onRetry={() => undefined} />);
    expect(screen.getByRole("img", { name: "ai.typing" })).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Looking at your sales");
  });
  it("types the answer out, lets a click show it all, and offers how I know only when it is complete", () => {
    const sources = [{ tool: "pos_sales_summary", params: {}, rows: [], summary: {} }];
    render(<ZiiraBubble message={{ ...base, state: "done", text: "Sales were 116.00. Well done today.", sources }} onRetry={() => undefined} />);
    expect(screen.queryByText("ai.howIKnow")).toBeNull();
    act(() => { vi.advanceTimersByTime(30); });
    expect(screen.getByText(/^Sales/, { selector: "p[aria-hidden]" }).textContent).toBe("Sales ");
    fireEvent.click(screen.getByText("ai.showAll"));
    expect(screen.getByText("Sales were 116.00. Well done today.", { selector: "p[aria-hidden]" })).toBeTruthy();
    expect(screen.getByText("ai.howIKnow")).toBeTruthy();
  });
  it("shows an answer restored from the tab's memory at once, and warns about unchecked figures", () => {
    render(<ZiiraBubble message={{ ...base, fresh: false, state: "done", text: "It was 5.", flagged: true }} onRetry={() => undefined} />);
    expect(screen.getByText("It was 5.")).toBeTruthy();
    expect(screen.getByText("ai.checkFigures")).toBeTruthy();
  });
  it("shows an error in plain words with Try again, and a stopped answer as stopped", () => {
    const retry = vi.fn();
    const { rerender } = render(<ZiiraBubble message={{ ...base, state: "error", error: "I could not reach the assistant." }} onRetry={retry} />);
    expect(screen.getByText(/I could not reach/)).toBeTruthy();
    fireEvent.click(screen.getByText("ai.retry"));
    expect(retry).toHaveBeenCalled();
    rerender(<ZiiraBubble message={{ ...base, state: "stopped", text: "Part. ", fresh: false }} onRetry={retry} />);
    expect(screen.getByText("ai.stopped")).toBeTruthy();
  });
  it("renders your own line, and still dots when motion is reduced", () => {
    render(<><UserBubble message={{ id: "u", role: "user", text: "Hello", state: "done" }} /><TypingDots /></>);
    expect(screen.getByText("Hello")).toBeTruthy();
    expect(screen.getByRole("img", { name: "ai.typing" }).querySelector(".motion-safe\\:animate-bounce")).toBeTruthy();
  });
});
