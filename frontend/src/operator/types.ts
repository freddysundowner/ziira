import type { Schemas } from "@/sdk";

/**
 * Names the API shares with the business app's own schemas (a plan, an invoice, a payment ...) are generated with their
 * module path in front. This puts that in one place.
 */
type Qualified = "CancelIn" | "InvoiceIn" | "InvoiceOut" | "PaymentIn" | "PaymentOut" | "PlanOut" | "PriceIn" | "PriceOut" | "ReasonIn" | "RequestOut" | "RoleOut";

export type PlatformSchema<K extends Qualified> = Schemas[`Platform${K}`];
