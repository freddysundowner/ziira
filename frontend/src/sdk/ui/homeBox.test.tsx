import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HomeBox } from "./homeBox";

afterEach(cleanup);
const at = (ui: React.ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe("HomeBox", () => {
  it("shows a number and one context line in a tile, linking to its screen", () => {
    at(<HomeBox variant="stat" to="/claims" value={7} hint="2 offers to answer" />);
    expect(screen.getByText("7")).toBeTruthy();
    expect(screen.getByText("2 offers to answer")).toBeTruthy();
    expect(screen.getByRole("link").getAttribute("href")).toBe("/claims");
  });
  it("keeps the 0 in a tile when there is nothing, with the clear line under it (the tile never disappears)", () => {
    at(<HomeBox variant="stat" to="/x" value={0} clear="Nothing waiting." />);
    expect(screen.getByText("0")).toBeTruthy();
    expect(screen.getByText("Nothing waiting.")).toBeTruthy();
  });
  it("collapses the full box to the one-line all-clear text when there is nothing", () => {
    const { container } = at(<HomeBox to="/x" value={0} clear="Nothing waiting." rows={[{ key: "a", left: "x" }]} />);
    expect(container.querySelector("[data-clear]")?.textContent).toBe("Nothing waiting.");
    expect(screen.queryByRole("list")).toBeNull();
  });
  it("lists rows with a short value at the right and a link to the screen", () => {
    at(<HomeBox to="/x" value={2} rows={[{ key: "a", left: "Ann · Cut", right: "3 d late" }, { key: "b", left: "Bob" }]} openLabel="Open it" />);
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("3 d late")).toBeTruthy();
    expect(screen.getByText("Open it").getAttribute("href")).toBe("/x");
  });
  it("shows the error with a way to try again, in both shapes", () => {
    const retry = vi.fn();
    at(<HomeBox variant="stat" to="/x" value={0} error="The server had a problem." onRetry={retry} />);
    expect(screen.getByRole("alert").textContent).toContain("The server had a problem.");
    fireEvent.click(screen.getByRole("button"));
    expect(retry).toHaveBeenCalledOnce();
  });
  it("shows a placeholder while loading, never a wrong 0", () => {
    at(<HomeBox variant="stat" to="/x" value={0} loading />);
    expect(screen.queryByText("0")).toBeNull();
  });
  it("keeps a long value inside its box (wraps instead of overflowing)", () => {
    at(<HomeBox to="/x" value="KES 12,345,678.00" />);
    expect(screen.getByText("KES 12,345,678.00").className).toContain("overflow-wrap:anywhere");
  });
});
