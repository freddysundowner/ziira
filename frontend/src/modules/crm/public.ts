/** What other modules may use from CRM: links to a customer and the slot names it offers. */

/** Page of one customer. */
export const customerPath = (customerId: string): string => `/customers/${customerId}`;

/** Tabs on a customer's page. Contributions receive { customerId: string, companyId: string }. */
export const CUSTOMER_TABS = "crm.customer.tabs";
