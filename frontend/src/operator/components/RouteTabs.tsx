import { NavLink } from "react-router-dom";

import { cx } from "@/sdk";

/** Tabs that are pages of their own (the address says which one is open, so a link or a reload lands on it). */
export function RouteTabs({ label, tabs }: { label: string; tabs: { to: string; label: string; end?: boolean }[] }) {
  return (
    <nav aria-label={label} className="tab-strip mb-4">
      {tabs.map((tab) => (
        <NavLink key={tab.to} to={tab.to} end={tab.end}
          className={({ isActive }) => cx("-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors", isActive ? "border-brand text-ink" : "border-transparent text-muted hover:text-ink")}>
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
