/** What other modules may use from Time and Billing: links to its pages. */

/** A person's own week of time. */
export const MY_WEEK_PATH = "/time";

/** A project's page. */
export const projectPath = (projectId: string): string => `/projects/${projectId}`;

/** An invoice review (the draft invoice made from approved time). */
export const invoiceReviewPath = (reviewId: string): string => `/time/reviews/${reviewId}`;
