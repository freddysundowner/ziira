/** Pay terms and bank details are proposed by one person and decided by another: where one stands. */
export function approvalState(row: { approved_by: string | null; rejected: boolean }): "approved" | "rejected" | "pending" {
  if (row.rejected) return "rejected";
  return row.approved_by ? "approved" : "pending";
}
