/** Links other modules may use to reach Purchasing screens. */
export const supplierPath = (supplierId: string): string => `/suppliers/${supplierId}`;
export const billPath = (billId: string): string => `/bills/${billId}`;
export const orderPath = (orderId: string): string => `/orders/${orderId}`;
