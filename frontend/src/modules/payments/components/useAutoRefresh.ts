import { useEffect, useRef } from "react";

/** Calls `refresh` every few seconds while `active` (for example while a payment prompt is still pending). */
export function useAutoRefresh(active: boolean, refresh: () => void, everyMs = 4000): void {
  const latest = useRef(refresh);
  latest.current = refresh;
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => latest.current(), everyMs);
    return () => window.clearInterval(id);
  }, [active, everyMs]);
}
