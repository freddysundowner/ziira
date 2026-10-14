/** What other modules may use from Point of Sale: where to send a person to see a sale or a till. */

export const saleHref = (saleId: string): string => `/pos/sales/${saleId}`;
export const tillHref = (tillId: string): string => `/pos/tills/${tillId}`;
