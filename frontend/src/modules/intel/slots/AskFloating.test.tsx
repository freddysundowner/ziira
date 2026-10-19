import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import intel from "../module";
import { openAskZiira } from "../public";
import AskFloating from "./AskFloating";

vi.mock("../components/AskBox", () => ({ default: () => <textarea aria-label="question" /> }));
vi.mock("../components/AiBadge", () => ({ default: () => null }));

const at = (path: string) => render(<MemoryRouter initialEntries={[path]}><AskFloating /></MemoryRouter>);
beforeEach(() => sessionStorage.clear());
afterEach(cleanup);

describe("floating Ask Ziira", () => {
  it("is a button that opens a panel and Escape closes it, returning focus to the button", () => {
    at("/products");
    const button = screen.getByRole("button", { name: "ai.askTitle" });
    expect(button.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(button);
    expect(screen.getByRole("dialog", { name: "ai.askTitle" })).toBeTruthy();
    expect(button.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(button);
  });
  it("remembers it was open in this tab", () => {
    const first = at("/");
    fireEvent.click(screen.getByRole("button", { name: "ai.askTitle" }));
    first.unmount();
    at("/");
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
  it("opens from the public open call", () => {
    at("/");
    act(() => openAskZiira());
    expect(screen.getByRole("dialog")).toBeTruthy();
  });
  it("is not shown on the till terminal page", () => {
    at("/pos/terminal");
    expect(screen.queryByRole("button")).toBeNull();
  });
  it("is offered by the intelligence module only to people who may ask (the shell hides it when the unit is off)", () => {
    const [floating] = intel.slots?.["shell.floating"] ?? [];
    expect(floating?.permission).toBe("ai.ask");
    expect(intel.unit).toBe("intel");
  });
});
