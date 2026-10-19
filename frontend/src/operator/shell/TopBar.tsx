import { LogOut, Menu as MenuIcon, Moon, Search, Settings2, Sun, UserCog } from "lucide-react";

import { Badge, LANGUAGES, Menu, setLanguage, type Theme, useTheme, useTranslation } from "@/sdk";
import { useNavigate } from "react-router-dom";

import { useOperatorMe } from "../me";
import { useOperator } from "../session";
import { AlertsBell } from "./AlertsBell";
import { useSetup } from "./data";

const initials = (name: string | undefined) => (name ?? "?").split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";

/** Light or dark, remembered in this browser (not offered where the browser cannot tell the device's preference). */
function ThemeToggle() {
  const { t } = useTranslation("operator");
  const [theme, setTheme] = useTheme();
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button type="button" onClick={() => setTheme(next)} aria-label={t(next === "dark" ? "shell.theme.dark" : "shell.theme.light")} title={t(next === "dark" ? "shell.theme.dark" : "shell.theme.light")}
      className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-sunken hover:text-ink focus-visible:ring-2 focus-visible:ring-brand">
      {next === "dark" ? <Moon className="h-4 w-4" aria-hidden /> : <Sun className="h-4 w-4" aria-hidden />}
    </button>
  );
}

/** The bar across the top: menu button on a phone, search, environment, language, alerts and the account menu. */
export function TopBar({ onMenu, onSearch }: { onMenu: () => void; onSearch: () => void }) {
  const { t, i18n } = useTranslation("operator");
  const { signOut } = useOperator();
  const navigate = useNavigate();
  const me = useOperatorMe();
  const setup = useSetup();
  const environment = setup.data?.environment;
  const isMac = typeof navigator !== "undefined" && /mac/i.test(navigator.platform);
  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-2 border-b border-line bg-surface/95 px-3 backdrop-blur sm:gap-3 sm:px-6 lg:h-[76px] lg:px-7">
      <button type="button" aria-label={t("nav.menu")} onClick={onMenu} className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-muted hover:bg-sunken hover:text-ink focus-visible:ring-2 focus-visible:ring-brand lg:hidden">
        <MenuIcon className="h-5 w-5" aria-hidden />
      </button>
      <button type="button" onClick={onSearch} aria-label={t("shell.search.open")} aria-keyshortcuts="Control+K Meta+K"
        className="flex h-10 min-w-0 flex-1 items-center gap-2 rounded-[10px] border border-line bg-bg px-3.5 text-left text-sm text-muted hover:border-muted/50 focus-visible:ring-2 focus-visible:ring-brand sm:max-w-[460px]">
        <Search className="h-4 w-4 shrink-0" aria-hidden />
        <span className="min-w-0 flex-1 truncate">{t("shell.search.placeholder")}</span>
        <kbd className="hidden rounded border border-line px-1.5 py-0.5 text-[11px] sm:block">{isMac ? "⌘K" : "Ctrl K"}</kbd>
      </button>
      <div className="flex-1" />
      {environment && <Badge tone={environment === "production" ? "bad" : "info"} className="hidden sm:inline-flex">{t(`shell.env.${environment}`, environment)}</Badge>}
      <select aria-label={t("language")} value={i18n.language} onChange={(e) => setLanguage(e.target.value as keyof typeof LANGUAGES)}
        className="hidden h-9 rounded-lg border border-line bg-surface px-2 text-xs md:block">
        {Object.entries(LANGUAGES).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select>
      {typeof window.matchMedia === "function" && <ThemeToggle />}
      <AlertsBell />
      <Menu label={t("shell.account.menu")}
        trigger={
          <span className="flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-sunken">
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand-strong" aria-hidden>{initials(me.data?.name)}</span>
            <span className="hidden text-left leading-tight md:block"><span className="block text-xs font-medium">{me.data?.name}</span><span className="block text-[11px] text-muted">{me.data?.role ? t(`operators.roles.${me.data.role}`, me.data.role) : ""}</span></span>
          </span>
        }
        items={[
          { label: t("shell.account.profile"), icon: <UserCog className="h-4 w-4" />, onSelect: () => navigate("/operator/account") },
          { label: t("shell.account.changePassword"), icon: <Settings2 className="h-4 w-4" />, onSelect: () => navigate("/operator/account#password") },
          "separator",
          { label: t("signOut"), icon: <LogOut className="h-4 w-4" />, onSelect: () => void signOut() },
        ]} />
    </header>
  );
}
