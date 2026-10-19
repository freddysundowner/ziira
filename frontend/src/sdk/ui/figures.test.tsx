import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Figure, StatRow } from "./figures";

afterEach(cleanup);

describe("StatRow and Figure", () => {
  it("lets a row of figures wrap by itself and never grow past its card", () => {
    const { container } = render(<StatRow><Figure label="Za kuchukuliwa" value="1" /></StatRow>);
    const row = container.firstElementChild as HTMLElement;
    expect(row.className).toContain("auto-fit");
    expect(row.className).toContain("min-w-0");
  });
  it("keeps a very long figure inside its box: fluid size, tabular digits, wraps instead of overflowing", () => {
    render(<StatRow><Figure label="Unbilled" value="KES 12,345,678.00" /></StatRow>);
    const value = screen.getByText("KES 12,345,678.00");
    expect(value.className).toContain("tnum");
    expect(value.className).toContain("clamp(");
    expect(value.className).toContain("overflow-wrap:anywhere");
    expect((value.closest("div") as HTMLElement).className).toContain("min-w-0");
  });
  it("shows the label small and in sentence case, above the number", () => {
    render(<Figure label="To collect" value="4" />);
    const label = screen.getByText("To collect");
    expect(label.className).not.toContain("uppercase");
    expect(label.compareDocumentPosition(screen.getByText("4")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});
