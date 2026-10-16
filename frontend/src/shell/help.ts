/**
 * Links to the Help centre on the Ziira website (step-by-step guides). The address comes from `VITE_HELP_URL`
 * (for example https://ziira.example/help); when it is not set, no Help link is shown anywhere.
 */
const base = (import.meta.env.VITE_HELP_URL as string | undefined)?.trim().replace(/\/+$/, "");

/** The Help centre home, or a page below it ("sell/add-products-and-prices"); undefined when Help is not configured. */
export function helpUrl(path?: string): string | undefined {
  if (!base) return undefined;
  return path ? `${base}/${path.replace(/^\/+|\/+$/g, "")}/` : `${base}/`;
}

/** Which guide matches a Home checklist step (the step ids come from the editions file). */
export const GUIDE_FOR_STEP: Readonly<Record<string, string>> = {
  organisation: "get-started/set-up-your-business",
  users: "get-started/invite-your-team",
  products: "sell/add-products-and-prices",
  opening_stock: "sell/set-opening-stock",
  till: "sell/open-a-till-and-make-a-sale",
  sale: "sell/open-a-till-and-make-a-sale",
  suppliers: "buy/add-a-supplier",
  customers: "customers/add-customers",
  expense: "money/record-expenses",
  connect: "intelligence/connect-your-system",
  alerts: "intelligence/alerts-and-quiet-hours",
  findings: "intelligence/work-through-findings",
};
