import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { formatAnswer } from "./format";

const html = (text: string) => render(<p>{formatAnswer(text)}</p>).container.innerHTML;

describe("formatAnswer", () => {
  it("makes **bold** bold and list lines bullets, and keeps line breaks", () => {
    const out = html("Sales were **KES 100**.\n* Juja: 5\n- Ruiru: 6");
    expect(out).toContain('<strong class="font-semibold">KES 100</strong>');
    expect(out).toContain("• Juja: 5");
    expect(out).toContain("• Ruiru: 6");
    expect(out).toContain("\n");
  });
  it("leaves an unfinished ** as it is, and never writes HTML", () => {
    expect(html("Total **KES 1")).toContain("Total **KES 1");
    const out = html("<img src=x onerror=alert(1)> **b**");
    expect(out).not.toContain("<img");
    expect(out).toContain("&lt;img");
  });
});
