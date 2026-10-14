import type { Schemas } from "@/sdk";

/** The API shapes this module uses, named once so a backend rename is fixed in one place. */
export type Employee = Schemas["EmployeeOut"];
export type Terms = Schemas["TermsOut"];
export type PayItem = Schemas["PayItemOut"];
export type Bank = Schemas["ziira__modules__people__api__schemas__BankOut"];
export type Component = Schemas["ComponentOut"];
export type Rule = Schemas["ziira__modules__people__api__schemas__RuleOut"];
export type Shift = Schemas["ShiftOut"];
export type Attendance = Schemas["AttendanceOut"];
export type LeaveType = Schemas["LeaveTypeOut"];
export type Leave = Schemas["LeaveOut"];
export type Run = Schemas["ziira__modules__people__api__schemas__RunOut"];
export type RunException = Schemas["ExceptionOut"];
export type PayslipSummary = Schemas["PayslipSummaryOut"];
export type ReturnSummary = Schemas["ziira__modules__people__api__schemas__ReturnSummaryOut"];
export type ReturnDetail = Schemas["ziira__modules__people__api__schemas__ReturnOut"];
export type TaxCard = Schemas["TaxCardOut"];
export type PaymentRow = Schemas["PaymentRowOut"];
export type PayslipDoc = Schemas["PayslipPrintOut"];

/** The run's `totals` is free-form JSON on the API; these are the keys payroll fills in. */
export interface RunTotals {
  employees?: number;
  gross_cash?: string;
  benefits?: string;
  total_deductions?: string;
  net_pay?: string;
  employer_cost?: string;
  other_deductions?: string;
}

export const totalsOf = (run: Run): RunTotals => run.totals as RunTotals;

