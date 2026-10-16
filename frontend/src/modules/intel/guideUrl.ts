/** Link to the website's complete guide to Intelligence. Base: VITE_SITE_URL, else VITE_HELP_URL without its trailing /help; unset: no link. */
export function guideUrl(): string | undefined {
  const site = (import.meta.env.VITE_SITE_URL as string | undefined)?.trim() || (import.meta.env.VITE_HELP_URL as string | undefined)?.trim().replace(/\/+$/, "").replace(/\/help$/, "");
  return site ? `${site.replace(/\/+$/, "")}/intelligence/complete-guide/` : undefined;
}
