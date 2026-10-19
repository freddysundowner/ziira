/** What other modules may use from Claims: the claim panel for a job or appointment page, and links to its pages. */

export { ClaimPanel, type ClaimPanelProps } from "./components/ClaimPanel";

/** Page of one claim. */
export const claimHref = (claimId: string): string => `/claims/${claimId}`;

/** The list of claims. */
export const CLAIMS_PATH = "/claims";
