import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NoticeStrip } from "./NoticeStrip";

afterEach(cleanup);

describe("NoticeStrip", () => {
  it("is a slim line with the message and one link, not a card", () => {
    const { container } = render(<MemoryRouter><NoticeStrip tone="info" to="/admin/billing" action="Open Plan & billing">Your free trial ends soon.</NoticeStrip></MemoryRouter>);
    expect(screen.getByText("Your free trial ends soon.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open Plan & billing" }).getAttribute("href")).toBe("/admin/billing");
    expect(container.querySelector("section, [class*=shadow-card], [class*=rounded-xl]")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
  it("can be hidden only when a way to hide it is given", () => {
    const hide = vi.fn();
    render(<MemoryRouter><NoticeStrip tone="warn" to="/x" action="Open" onDismiss={hide}>Soon.</NoticeStrip></MemoryRouter>);
    fireEvent.click(screen.getByRole("button"));
    expect(hide).toHaveBeenCalled();
  });
});
