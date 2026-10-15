import { Link } from "react-router-dom";

import { Card, cx, iconFor, Slot, useAccess, useActiveModules, useSession, useTranslation, visibleMenu } from "@/sdk";

/** The home page: a greeting, shortcuts to the screens you may open, and boxes that modules add through the "dashboard.widgets" slot. */
export function Home() {
  const { t } = useTranslation();
  const { me } = useSession();
  const items = visibleMenu(useActiveModules(), useAccess()).filter((i) => i.group && i.group !== "admin").slice(0, 8);
  const hour = new Date().getHours();
  const greeting = hour < 12 ? t("home.morning") : hour < 18 ? t("home.afternoon") : t("home.evening");
  const first = me?.full_name?.split(/\s+/)[0];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">{greeting}{first ? `, ${first}` : ""}</h1>
        <p className="mt-1 text-sm text-muted">{t("home.subtitle")}</p>
      </div>
      {items.length > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {items.map((i) => {
            const I = iconFor(i.icon);
            return (
              <Link key={i.to} to={i.to} className="group flex items-center gap-3 rounded-xl border border-line bg-surface p-3.5 shadow-card transition-colors hover:border-brand/50">
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-soft text-brand-strong"><I className="h-[18px] w-[18px]" /></span>
                <span className="text-sm font-medium">{t(i.label)}</span>
              </Link>
            );
          })}
        </div>
      )}
      {/* grid-cols-1 (not an automatic column) lets a wide widget shrink instead of widening the page on a phone */}
      <div className={cx("grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3")}>
        <Slot
          name="dashboard.widgets"
          render={(c, content) => <Card className="min-w-0" title={c.label ? t(c.label) : undefined}>{content}</Card>}
        />
      </div>
    </div>
  );
}
