import type { ReactNode } from "react";

import { useTranslation } from "@/sdk";

/** The frame of the signed-out screens: a brand panel beside the form on a wide screen, the form alone on a phone. */
export function AuthShell({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1fr)_minmax(0,480px)]">
      <div className="relative hidden overflow-hidden bg-brand-strong p-12 text-brand-ink lg:flex lg:flex-col lg:justify-between">
        <div className="absolute -right-24 -top-24 h-96 w-96 rounded-full bg-white/10" />
        <div className="absolute -bottom-32 -left-16 h-[28rem] w-[28rem] rounded-full bg-black/10" />
        <div className="relative flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/20 text-lg font-bold">Z</div>
          <span className="text-xl font-semibold">{t("appName")}</span>
        </div>
        <div className="relative max-w-md space-y-3">
          <p className="text-3xl font-semibold leading-tight">{t("auth.tagline")}</p>
          <p className="text-base opacity-90">{t("auth.subtitle")}</p>
        </div>
        <p className="relative text-xs opacity-90">© {new Date().getFullYear()} Ziira</p>
      </div>
      <main className="flex items-center justify-center p-5 sm:p-10">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand font-bold text-brand-ink">Z</div>
            <span className="text-lg font-semibold">{t("appName")}</span>
          </div>
          {children}
        </div>
      </main>
    </div>
  );
}
