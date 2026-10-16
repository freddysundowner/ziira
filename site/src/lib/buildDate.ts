/** The day this build ran (UTC, YYYY-MM-DD): shown as "Last reviewed" on the complete guide and used as its sitemap lastmod and dateModified.
 *  `SITE_BUILD_DATE` fixes it for reproducible builds and tests. */
export const BUILD_DATE: string = /^\d{4}-\d{2}-\d{2}$/.test(process.env.SITE_BUILD_DATE ?? "") ? (process.env.SITE_BUILD_DATE as string) : new Date().toISOString().slice(0, 10);
/** The day the guide was first published (fixed). */
export const GUIDE_PUBLISHED = "2026-10-16";
