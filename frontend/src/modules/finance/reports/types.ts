import type { Scope } from "../scope";

/** What every report tab gets from the filter bar. `to` is also the "as of" date for balance reports. */
export interface ReportProps {
  scope: Scope;
  from: string;
  to: string;
}
