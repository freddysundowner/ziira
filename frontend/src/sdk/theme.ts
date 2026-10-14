import { useCallback, useEffect, useState } from "react";

import { readStored, writeStored } from "./storage";

export type Theme = "light" | "dark" | "system";
const KEY = "ziira.theme";

function apply(theme: Theme): void {
  const dark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.classList.toggle("dark", dark);
}

/** Light, dark or follow the device. Remembered in this browser. */
export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => (readStored(KEY) as Theme | null) ?? "system");
  useEffect(() => {
    apply(theme);
    if (theme !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => apply("system");
    media.addEventListener("change", on);
    return () => media.removeEventListener("change", on);
  }, [theme]);
  const set = useCallback((t: Theme) => { writeStored(KEY, t === "system" ? null : t); setTheme(t); }, []);
  return [theme, set];
}
