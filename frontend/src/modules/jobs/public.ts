/** What other modules may use from Jobs: links to a job and to an item customers brought in. */

/** Page of one job (work order). */
export const jobHref = (jobId: string): string => `/jobs/${jobId}`;

/** Page of one item customers brought in (a vehicle, phone, appliance...) with its job history. */
export const assetHref = (assetId: string): string => `/jobs/items/${assetId}`;
