import type { Schemas } from "@/sdk";

export type Job = Schemas["JobOut"];
export type JobSummary = Schemas["JobSummaryOut"];
export type Stage = Schemas["StatusOut"];
export type StageRef = Schemas["StatusRef"];
export type Board = Schemas["BoardOut"];
export type Asset = Schemas["AssetOut"];
export type AssetDetail = Schemas["AssetDetailOut"];
export type Estimate = Schemas["EstimateOut"];
export type EstimateLine = Schemas["EstimateLineOut"];
export type Part = Schemas["PartOut"];
export type Labour = Schemas["LabourOut"];
export type Person = Schemas["PersonOut"];
export type JobEvent = Schemas["JobEventOut"];
export type JobSettings = Schemas["JobSettingsOut"];
export type Template = Schemas["JobTemplateOut"];
export type WorkType = Schemas["JobWorkTypeOut"];
export type LabourTask = Schemas["JobTaskLibraryOut"];
export type PartCategory = Schemas["JobPartCategoryOut"];
export type JobType = Schemas["JobTypeOut"];
export type PhotoCategory = Schemas["JobPhotoCategoryOut"];
export type Bay = Schemas["JobBayOut"];
export type BayBooking = Schemas["JobBayBookingOut"];
export type Loan = Schemas["JobLoanOut"];
export type Visit = Schemas["JobVisitOut"];
export type ServiceDue = Schemas["JobServiceDueOut"];
export type Technician = Schemas["JobTechnicianOut"];
export type PackStep = Schemas["JobPackStepOut"];
export type ClaimInfo = Schemas["JobClaimOut"];

/** The roles a stage can hold (the platform moves jobs into them when something happens). */
export const ROLES = ["initial", "quoted", "approved", "ready", "collected", "closed", "cancelled"] as const;
/** What a stage means for the work: still going, waiting on someone, finished, or over. */
export const KINDS = ["open", "waiting", "done", "closed"] as const;
export type StageKind = (typeof KINDS)[number];
