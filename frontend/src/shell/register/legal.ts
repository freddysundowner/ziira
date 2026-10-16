/** Where the terms and the privacy policy live (the marketing site): set at build time, and the links are left out when unset. */
export const LEGAL = {
  terms: (import.meta.env.VITE_TERMS_URL as string | undefined)?.trim() || "",
  privacy: (import.meta.env.VITE_PRIVACY_URL as string | undefined)?.trim() || "",
};
