"""API schema names must be unique across the whole API.

When two pydantic classes share a name, the OpenAPI generator renames both to a long `ziira__module__path__Name`
form, which breaks the web code that uses the short name. Give every new request/response class a unique name
(a module prefix such as `Booking`, `Job`, `TimeBilling`, `Membership`).

`LEGACY` lists the older duplicates that existed before the service modules and that the web code already
references by their long names; it must never grow.
"""

from ziira.kernel.app import create_app

LEGACY = {
    "ziira__kernel__api__notification_routes__TestIn",
    "ziira__kernel__api__operator_ai_routes__AiUsageOut",
    "ziira__kernel__api__operator_email_routes__ActiveIn",
    "ziira__kernel__api__operator_email_routes__TestIn",
    "ziira__kernel__api__privacy_routes__RequestIn",
    "ziira__kernel__api__privacy_routes__RequestOut",
    "ziira__kernel__api__schemas__ActiveIn",
    "ziira__kernel__api__schemas__ReasonIn",
    "ziira__kernel__api__schemas__RequestOut",
    "ziira__kernel__api__schemas__RuleIn",
    "ziira__kernel__api__schemas__RuleOut",
    "ziira__modules__finance__api__schemas__AccountIn",
    "ziira__modules__finance__api__schemas__AccountOut",
    "ziira__modules__finance__api__schemas__AccountUpdateIn",
    "ziira__modules__finance__api__schemas__MappingIn",
    "ziira__modules__finance__api__schemas__ReverseIn",
    "ziira__modules__finance__api__schemas__RuleIn",
    "ziira__modules__finance__api__schemas__RuleOut",
    "ziira__modules__finance__api__schemas__RuleUpdateIn",
    "ziira__modules__finance__api__schemas__StatementLineOut",
    "ziira__modules__imports__api__schemas__MappingIn",
    "ziira__modules__imports__api__schemas__ReverseIn",
    "ziira__modules__intel__api__schemas__AiUsageOut",
    "ziira__modules__intel__api__schemas__RejectIn",
    "ziira__modules__intel__api__schemas__RuleIn",
    "ziira__modules__intel__api__schemas__RuleOut",
    "ziira__modules__intel__api__schemas__RuleUpdateIn",
    "ziira__modules__intel__api__schemas__RunIn",
    "ziira__modules__intel__api__schemas__RunOut",
    "ziira__modules__inventory__api__schemas__BalanceOut",
    "ziira__modules__payments__api__schemas__AccountIn",
    "ziira__modules__payments__api__schemas__AccountOut",
    "ziira__modules__payments__api__schemas__AccountUpdateIn",
    "ziira__modules__payments__api__schemas__ReasonIn",
    "ziira__modules__payments__api__schemas__StatementIn",
    "ziira__modules__people__api__schemas__BankIn",
    "ziira__modules__people__api__schemas__BankOut",
    "ziira__modules__people__api__schemas__PrintLineOut",
    "ziira__modules__people__api__schemas__RejectIn",
    "ziira__modules__people__api__schemas__ReturnOut",
    "ziira__modules__people__api__schemas__ReturnSummaryOut",
    "ziira__modules__people__api__schemas__RuleIn",
    "ziira__modules__people__api__schemas__RuleOut",
    "ziira__modules__people__api__schemas__RunIn",
    "ziira__modules__people__api__schemas__RunOut",
    "ziira__modules__pos__api__schemas__BalanceOut",
    "ziira__modules__pos__api__schemas__OrderIn",
    "ziira__modules__pos__api__schemas__PrintLineOut",
    "ziira__modules__pos__api__schemas__ReasonIn",
    "ziira__modules__pos__api__schemas__ReceiptIn",
    "ziira__modules__pos__api__schemas__ReceiptOut",
    "ziira__modules__pos__api__schemas__ReceiptSummaryOut",
    "ziira__modules__pos__api__schemas__RefundIn",
    "ziira__modules__pos__api__schemas__RefundOut",
    "ziira__modules__pos__api__schemas__ReturnIn",
    "ziira__modules__pos__api__schemas__ReturnLineIn",
    "ziira__modules__pos__api__schemas__ReturnLineOut",
    "ziira__modules__pos__api__schemas__ReturnOut",
    "ziira__modules__pos__api__schemas__ReturnSummaryOut",
    "ziira__modules__pos__api__schemas__StatementLineOut",
    "ziira__modules__products__api__schemas__PriceOut",
    "ziira__modules__purchasing__api__schemas__BankIn",
    "ziira__modules__purchasing__api__schemas__BankOut",
    "ziira__modules__purchasing__api__schemas__OrderIn",
    "ziira__modules__purchasing__api__schemas__PriceOut",
    "ziira__modules__purchasing__api__schemas__ReceiptIn",
    "ziira__modules__purchasing__api__schemas__ReceiptOut",
    "ziira__modules__purchasing__api__schemas__ReceiptSummaryOut",
    "ziira__modules__purchasing__api__schemas__RefundIn",
    "ziira__modules__purchasing__api__schemas__RefundOut",
    "ziira__modules__purchasing__api__schemas__RequestIn",
    "ziira__modules__purchasing__api__schemas__RequestOut",
    "ziira__modules__purchasing__api__schemas__ReturnIn",
    "ziira__modules__purchasing__api__schemas__ReturnLineIn",
    "ziira__modules__purchasing__api__schemas__ReturnLineOut",
    "ziira__modules__purchasing__api__schemas__ReturnOut",
    "ziira__modules__purchasing__api__schemas__ReturnSummaryOut",
    "ziira__modules__purchasing__api__schemas__ReverseIn",
    "ziira__modules__purchasing__api__schemas__StatementIn",
}


def test_no_new_prefixed_schema_names() -> None:
    schemas = create_app().openapi()["components"]["schemas"]
    prefixed = {name for name in schemas if name.startswith("ziira__")}
    new = sorted(prefixed - LEGACY)
    assert not new, f"duplicate class names now prefixed by the generator (rename them uniquely): {new}"
