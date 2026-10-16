/** The kinds of message a person can choose a channel for (the API's names). */
export const KINDS = ["alerts", "brief", "approvals"] as const;
export type Kind = (typeof KINDS)[number];
