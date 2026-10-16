import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { linksFrom } from "./publicConfig";
import { SignUpClosed } from "./SignUpClosed";

afterEach(cleanup);

describe("sign-up states", () => {
  it("says sign-up is closed and links to the contact", () => {
    render(<MemoryRouter><SignUpClosed invite={false} support="help@example.test" /></MemoryRouter>);
    expect(screen.getByRole("heading").textContent).toMatch(/closed/i);
    expect(screen.getByRole("link", { name: /help@example.test/ }).getAttribute("href")).toBe("mailto:help@example.test");
  });
  it("says it is by invitation only", () => {
    render(<MemoryRouter><SignUpClosed invite support="" /></MemoryRouter>);
    expect(screen.getByRole("heading").textContent).toMatch(/invitation/i);
    expect(screen.queryByText(/mailto/)).toBeNull();
  });
  it("takes links from the platform settings and leaves them empty when nothing is set", () => {
    const links = linksFrom({ terms_url: "https://x.test/terms", privacy_url: "", help_url: "", site_url: "", support_email: "a@x.test" });
    expect(links.terms).toBe("https://x.test/terms");
    expect(links.support).toBe("a@x.test");
    expect(linksFrom(undefined).support).toBe("");
  });
});
