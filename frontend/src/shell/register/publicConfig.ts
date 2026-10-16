import { useQuery } from "@tanstack/react-query";

import { api, unwrap } from "@/sdk";

const env = (value: unknown): string => (typeof value === "string" ? value.trim() : "");

/** What the platform says about sign-up and its links (Super Admin > Platform > Settings). Failing to ask is not a reason to block sign-up. */
export function usePublicConfig() {
  return useQuery({ queryKey: ["public-config"], queryFn: () => unwrap(api.GET("/api/v1/public/config")), staleTime: 60_000, retry: 0 });
}

export interface Links { terms: string; privacy: string; help: string; site: string; support: string }

/** The links from the platform settings, each falling back to the build-time `VITE_*` value. */
export function linksFrom(config: { terms_url: string; privacy_url: string; help_url: string; site_url: string; support_email: string } | undefined): Links {
  return {
    terms: config?.terms_url || env(import.meta.env.VITE_TERMS_URL),
    privacy: config?.privacy_url || env(import.meta.env.VITE_PRIVACY_URL),
    help: config?.help_url || env(import.meta.env.VITE_HELP_URL),
    site: config?.site_url || env(import.meta.env.VITE_SITE_URL),
    support: config?.support_email ?? "",
  };
}
