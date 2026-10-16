import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import type { NavItem } from "@/sdk";

import { PageLink } from "./Sidebar";

afterEach(cleanup);

const till = { label: "pos:terminal.menu", to: "/pos/terminal", primary: true, icon: "sales" } as NavItem;
const page = { label: "pos:sales", to: "/pos/sales", icon: "sales" } as NavItem;
const draw = (item: NavItem, current: boolean) => render(<MemoryRouter><PageLink item={item} current={current} /></MemoryRouter>);

describe("sidebar active state", () => {
  it("highlights Point of sale only on the till route", () => {
    draw(till, false);
    const idle = screen.getByRole("link");
    expect(idle.getAttribute("aria-current")).toBeNull();
    expect(idle.className).not.toContain("bg-brand-strong");
    cleanup();
    draw(till, true);
    const open = screen.getByRole("link");
    expect(open.getAttribute("aria-current")).toBe("page");
    expect(open.className).toContain("bg-brand-strong");
  });
  it("marks an ordinary page current only when it is", () => {
    draw(page, false);
    expect(screen.getByRole("link").getAttribute("aria-current")).toBeNull();
  });
});
