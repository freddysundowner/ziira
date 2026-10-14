import { Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { cx, iconFor, Modal, useTranslation, type MenuItem } from "@/sdk";

/** Ctrl/Cmd + K: jump to any screen you may open. */
export function CommandPalette({ open, onClose, items, onGo }: { open: boolean; onClose: () => void; items: MenuItem[]; onGo: (to: string) => void }) {
  const { t } = useTranslation();
  const [text, setText] = useState("");
  const [active, setActive] = useState(0);
  useEffect(() => { if (open) { setText(""); setActive(0); } }, [open]);
  const all = useMemo(() => [{ label: "home.menu", to: "/", icon: "home" } as MenuItem, ...items], [items]);
  const found = all.filter((i) => t(i.label).toLowerCase().includes(text.trim().toLowerCase()));
  return (
    <Modal open={open} onClose={onClose} title={t("search")} size="sm">
      <div className="relative">
        <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted" />
        <input data-autofocus value={text} onChange={(e) => { setText(e.target.value); setActive(0); }} placeholder={t("searchScreens")} aria-label={t("search")}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, found.length - 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
            if (e.key === "Enter" && found[active]) onGo(found[active].to);
          }}
          className="h-10 w-full rounded-lg border border-line bg-bg pl-9 pr-3 text-sm" />
      </div>
      <ul className="mt-3 max-h-72 space-y-0.5 overflow-y-auto">
        {found.length === 0 && <li className="py-6 text-center text-sm text-muted">{t("nothingFound")}</li>}
        {found.map((i, n) => {
          const I = iconFor(i.icon);
          return (
            <li key={i.to}>
              <button onMouseEnter={() => setActive(n)} onClick={() => onGo(i.to)} className={cx("flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm", n === active && "bg-sunken")}>
                <I className="h-4 w-4 text-muted" />{t(i.label)}
              </button>
            </li>
          );
        })}
      </ul>
    </Modal>
  );
}
