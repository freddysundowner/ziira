/** What other modules may use from Memberships: links to a member. */

/** Page of one membership. */
export const memberPath = (memberId: string): string => `/memberships/${memberId}`;

/** Page that lists the plans and packages a business sells. */
export const cataloguePath = "/memberships/plans";

/** Page of the recurring invoices. */
export const recurringPath = "/memberships/recurring";

/** The person's page (a customer-centred view: profile, money, visits), for someone with or without a membership. */
export const personPath = (customerId: string): string => `/memberships/people/${customerId}`;

/** The front desk's check-in screen. */
export const checkinPath = "/memberships/checkin";

/** The full-screen check-in members use themselves. */
export const kioskPath = "/memberships/kiosk";

/** Who owes money. */
export const arrearsPath = "/memberships/arrears";

/** The owner's reports. */
export const reportsPath = "/memberships/reports";

/** Lockers, vouchers and credit, trainers. */
export const extrasPath = "/memberships/extras";
