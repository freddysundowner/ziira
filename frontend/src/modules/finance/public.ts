/** Where other modules can link to in Finance. */
export const financeLinks = {
  journalEntry: (entryId: string) => `/finance/journal/${entryId}`,
  expense: (expenseId: string) => `/finance/expenses/${expenseId}`,
  reports: "/finance/reports",
} as const;
