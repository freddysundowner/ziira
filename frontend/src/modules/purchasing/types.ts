import type { Schemas } from "@/sdk";


export type Supplier = Schemas["SupplierOut"];
export type Bank = Schemas["ziira__modules__purchasing__api__schemas__BankOut"];
export type SupplierPrice = Schemas["ziira__modules__purchasing__api__schemas__PriceOut"];
export type PurchaseRequest = Schemas["ziira__modules__purchasing__api__schemas__RequestOut"];
export type RequestSummary = Schemas["RequestSummaryOut"];
export type Order = Schemas["OrderOut"];
export type OrderSummary = Schemas["OrderSummaryOut"];
export type OrderLine = Schemas["OrderLineOut"];
export type Receipt = Schemas["ziira__modules__purchasing__api__schemas__ReceiptOut"];
export type ReceiptSummary = Schemas["ziira__modules__purchasing__api__schemas__ReceiptSummaryOut"];
export type Bill = Schemas["BillOut"];
export type BillSummary = Schemas["BillSummaryOut"];
export type PurchaseReturn = Schemas["ziira__modules__purchasing__api__schemas__ReturnOut"];
export type ReturnSummary = Schemas["ziira__modules__purchasing__api__schemas__ReturnSummaryOut"];
export type CreditNote = Schemas["CreditNoteOut"];
export type CreditNoteSummary = Schemas["CreditNoteSummaryOut"];
export type Refund = Schemas["ziira__modules__purchasing__api__schemas__RefundOut"];
export type RefundDue = Schemas["RefundDueOut"];
export type Payables = Schemas["PayablesOut"];
export type StatementRecon = Schemas["StatementReconOut"];
export type PayMethod = Schemas["PayBillIn"]["method"];
