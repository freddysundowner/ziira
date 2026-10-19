import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { WidgetCard } from "./WidgetCard";

afterEach(cleanup);

describe("WidgetCard", () => {
  it("leaves out the box when the widget renders nothing", () => {
    const { container } = render(<WidgetCard>{null}</WidgetCard>);
    expect((container.firstElementChild as HTMLElement).hidden).toBe(true);
  });
  it("shows the box with its title when the widget has content", () => {
    const { container } = render(<WidgetCard title="Today"><p>3 sales</p></WidgetCard>);
    expect((container.firstElementChild as HTMLElement).hidden).toBe(false);
    expect(screen.getByText("3 sales")).toBeTruthy();
    expect(screen.getByText("Today")).toBeTruthy();
  });
  it("shrinks a widget that has nothing to show into a one-line all-clear row at the end of its grid", () => {
    const { container } = render(<WidgetCard title="Waiting for approval"><p data-clear>Nothing waiting for you.</p></WidgetCard>);
    const box = container.firstElementChild as HTMLElement;
    expect(box.dataset.widget).toBe("clear");
    expect(box.className).toContain("col-span-full");
    expect(box.className).toContain("order-last");
    expect(screen.getByText("Nothing waiting for you.")).toBeTruthy();
  });
  it("keeps the full card when the widget has something to show", () => {
    const { container } = render(<WidgetCard title="Waiting"><p>3 requests</p></WidgetCard>);
    expect((container.firstElementChild as HTMLElement).dataset.widget).toBe("shown");
  });
});
