"""The chart of accounts template for a Kenyan small business, and the default posting rules. Pure data.

Accounts: (code, name, type, subtype, is_control). A control account is kept by a sub-ledger (stock, customers,
suppliers, mobile money), so people cannot post to it by hand.
"""

from typing import NamedTuple


class TemplateAccount(NamedTuple):
    code: str
    name: str
    type: str
    subtype: str | None
    is_control: bool = False


CHART: tuple[TemplateAccount, ...] = (
    TemplateAccount("1010", "Till cash", "asset", "cash"),
    TemplateAccount("1020", "Bank", "asset", "bank"),
    TemplateAccount("1030", "M-Pesa clearing", "asset", "mpesa_clearing", True),
    TemplateAccount("1040", "Card clearing", "asset", "card_clearing"),
    TemplateAccount("1100", "Accounts receivable", "asset", "receivable", True),
    TemplateAccount("1200", "Inventory", "asset", "inventory", True),
    TemplateAccount("1210", "Inventory in transit", "asset", "inventory_in_transit", True),
    TemplateAccount("1300", "VAT input", "asset", "vat_input"),
    TemplateAccount("2000", "Accounts payable", "liability", "payable", True),
    TemplateAccount("2100", "Goods received not invoiced", "liability", "grni", True),
    TemplateAccount("2200", "VAT output", "liability", "vat_output"),
    TemplateAccount("2900", "Stock transfer clearing", "liability", "transfer_clearing", True),
    TemplateAccount("3000", "Owner's equity", "equity", "equity"),
    TemplateAccount("3100", "Opening balance equity", "equity", "opening_equity"),
    TemplateAccount("3900", "Retained earnings", "equity", "retained_earnings"),
    TemplateAccount("4000", "Sales", "income", "sales"),
    TemplateAccount("4100", "Sales returns", "income", "sales_returns"),
    TemplateAccount("5000", "Cost of goods sold", "expense", "cogs"),
    TemplateAccount("5100", "Inventory shrinkage", "expense", "shrinkage"),
    TemplateAccount("5200", "Purchase price variance", "expense", "purchase_variance"),
    TemplateAccount("6000", "Rent", "expense", "rent"),
    TemplateAccount("6100", "Salaries and wages", "expense", "salaries"),
    TemplateAccount("6200", "Utilities", "expense", "utilities"),
    TemplateAccount("6300", "Transport", "expense", "transport"),
    TemplateAccount("6400", "Bank and M-Pesa charges", "expense", "bank_charges"),
    TemplateAccount("6500", "Cash shortages and overages", "expense", "till_variance"),
    TemplateAccount("6900", "Other expenses", "expense", "other_expense"),
)

JOURNALS: tuple[tuple[str, str], ...] = (
    ("SAL", "Sales"), ("PUR", "Purchases"), ("STK", "Stock"), ("CSH", "Cash and bank"), ("PAY", "Payroll"),
    ("GEN", "General"),
)

# Default posting rules: (document type, line role) -> account code, and the side the role normally takes.
# A document type is what the posting engine turns into entries; roles are named in domain/recipes.py.
DEFAULT_RULES: tuple[tuple[str, str, str, str], ...] = (
    ("stock_movement", "inventory", "1200", "debit"),
    ("stock_movement", "inventory_in_transit", "1210", "debit"),
    ("stock_movement", "cogs", "5000", "debit"),
    ("stock_movement", "grni", "2100", "credit"),
    ("stock_movement", "opening_equity", "3100", "credit"),
    ("stock_movement", "shrinkage", "5100", "debit"),
    ("stock_movement", "transfer_clearing", "2900", "credit"),
    ("sale", "cash", "1010", "debit"),
    ("sale", "mpesa", "1030", "debit"),
    ("sale", "card", "1040", "debit"),
    ("sale", "credit", "1100", "debit"),
    ("sale", "other", "1020", "debit"),
    ("sale", "sales", "4000", "credit"),
    ("sale", "vat_output", "2200", "credit"),
    ("sale_return", "cash", "1010", "credit"),
    ("sale_return", "mpesa", "1030", "credit"),
    ("sale_return", "card", "1040", "credit"),
    ("sale_return", "credit", "1100", "credit"),
    ("sale_return", "other", "1020", "credit"),
    ("sale_return", "sales_returns", "4100", "debit"),
    ("sale_return", "vat_output", "2200", "debit"),
    ("settlement", "bank", "1020", "debit"),
    ("settlement", "bank_charges", "6400", "debit"),
    ("settlement", "mpesa_clearing", "1030", "credit"),
    ("cash_deposit", "bank", "1020", "debit"),
    ("cash_deposit", "cash", "1010", "credit"),
    ("till_variance", "cash", "1010", "debit"),
    ("till_variance", "till_variance", "6500", "credit"),
    ("supplier_bill", "grni", "2100", "debit"),
    ("supplier_bill", "purchase_variance", "5200", "debit"),
    ("supplier_bill", "vat_input", "1300", "debit"),
    ("supplier_bill", "payable", "2000", "credit"),
    ("supplier_payment", "payable", "2000", "debit"),
    ("supplier_payment", "cash", "1010", "credit"),
    ("supplier_payment", "bank", "1020", "credit"),
    ("supplier_payment", "mpesa", "1030", "credit"),
    ("supplier_payment", "card", "1040", "credit"),
    ("supplier_payment", "other", "1020", "credit"),
    ("supplier_credit_note", "payable", "2000", "debit"),
    ("supplier_credit_note", "grni", "2100", "credit"),
    ("supplier_credit_note", "purchase_variance", "5200", "credit"),
    ("supplier_credit_note", "vat_input", "1300", "credit"),
    ("customer_payment", "receivable", "1100", "credit"),
    ("customer_payment", "cash", "1010", "debit"),
    ("customer_payment", "bank", "1020", "debit"),
    ("customer_payment", "mpesa", "1030", "debit"),
    ("customer_payment", "card", "1040", "debit"),
    ("customer_payment", "other", "1020", "debit"),
    ("expense", "vat_input", "1300", "debit"),
    ("expense", "cash", "1010", "credit"),
    ("expense", "bank", "1020", "credit"),
    ("expense", "mpesa", "1030", "credit"),
    ("expense", "card", "1040", "credit"),
    ("expense", "other", "1020", "credit"),
)
