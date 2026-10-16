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
});
