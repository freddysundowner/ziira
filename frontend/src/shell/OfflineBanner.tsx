import { WifiOff } from "lucide-react";
import { useEffect, useState } from "react";

import { useTranslation } from "@/sdk";

/** Says so when the browser loses its connection, so a failed save is understood. */
export function OfflineBanner() {
  const { t } = useTranslation();
  const [online, setOnline] = useState(typeof navigator === "undefined" ? true : navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true), off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); };
  }, []);
  if (online) return null;
  return (
    <div role="status" className="no-print flex items-center justify-center gap-2 bg-warn-soft px-3 py-1.5 text-xs font-medium text-warn">
      <WifiOff className="h-3.5 w-3.5" /> {t("offline")}
    </div>
  );
}
