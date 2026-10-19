import type { ReactNode } from "react";

import { Wordmark } from "@/sdk";

import { BrandPanel } from "./BrandPanel";

/** The frame of the signed-out screens: the navy brand panel with its line art beside the form on a wide screen, the form alone on a phone. */
export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1fr)_minmax(0,480px)]">
      <BrandPanel className="max-lg:hidden" />
      <main className="flex items-center justify-center p-5 sm:p-10">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center lg:hidden">
            <Wordmark tone="light" className="h-9 w-auto dark:hidden" />
            <Wordmark tone="dark" className="hidden h-9 w-auto dark:block" />
          </div>
          {children}
        </div>
      </main>
    </div>
  );
}
