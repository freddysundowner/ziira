"""CSV exports from any POS or ERP: sales, invoices, stock movements and expenses.

Each reads the columns the business maps (the usual names are guessed), so one file kind serves every system that can
export a spreadsheet. A sale may be one row (with its total) or one row per item (rows sharing a receipt number are one
sale). Re-uploading overlapping files adds nothing twice: records are keyed by their reference (the receipt or invoice
number, or a stable reference made from the row when the file has none).
"""

from decimal import Decimal
from typing import Literal

from ziira.modules.connect.connectors.files import (
    FileConnector,
    FileField,
    ParsedRow,
    RowReader,
    method_of,
    stable_ref,
)
from ziira.modules.connect.public import (
    Expense,
    Invoice,
    Party,
    Product,
    Record,
    Sale,
    SaleLine,
    SalePayment,
    StockMovement,
)

ZERO = Decimal(0)
StockKind = Literal["sale", "purchase", "adjustment", "transfer_in", "transfer_out", "count", "return", "other"]
VOID_WORDS = ("void", "cancel", "reverse", "deleted")
REFUND_WORDS = ("refund", "return", "credit note")


def _slug(text: str) -> str:
    return " ".join(text.lower().split())


def _status_of(word: str) -> Literal["posted", "voided", "refunded"]:
    low = word.lower()
    if any(w in low for w in VOID_WORDS):
        return "voided"
    if any(w in low for w in REFUND_WORDS):
        return "refunded"
    return "posted"

KIND_WORDS: tuple[tuple[StockKind, tuple[str, ...]], ...] = (
    ("count", ("count", "stock take", "stocktake", "reconcil")),
    ("adjustment", ("adjust", "write off", "writeoff", "damage", "loss", "shrink", "expired")),
    ("transfer_in", ("transfer in", "receipt from")),
    ("transfer_out", ("transfer out", "transfer")),
    ("return", ("return",)),
    ("purchase", ("purchase", "receipt", "grn", "goods in", "received")),
    ("sale", ("sale", "sold", "delivery", "issue", "dispatch")),
)


class CsvSales(FileConnector):
    kind = "csv_sales"
    title = "Sales export"
    description = ("A spreadsheet of sales from any till or POS: receipts with date, total, cashier, branch and how "
                   "they were paid.")
    entities = ("sales",)
    how_to = ("In your till or POS system, export the sales report as a CSV file (all receipts for a period, with the "
              "cashier, branch and payment method if it has them). Upload it here; upload a newer export whenever you "
              "like: sales already read are not counted twice.")
    fields = (
        FileField("receipt", "Receipt or sale number", True, ("receipt no", "sale no", "invoice no", "transaction id",
                                                              "order no", "number", "id", "bill no"),
                                                                  example="R-10234"),
        FileField("date", "Date (and time)", True, ("sale date", "date time", "datetime", "timestamp",
            "transaction date",
                                                    "created at", "sold at"), example="2026-10-14 13:45"),
        FileField("time", "Time (if separate from the date)", False, ("sale time",), example="13:45"),
        FileField("total", "Sale total", False, ("amount", "grand total", "total amount", "net total", "sale amount",
                                                  "total sales"), example="1250.00"),
        FileField("branch", "Branch or store", False, ("store", "outlet", "shop", "location", "site", "warehouse")),
        FileField("cashier", "Cashier", False, ("user", "served by", "operator", "sales person", "salesperson",
                                                 "employee", "created by", "clerk")),
        FileField("customer", "Customer", False, ("client", "customer name", "buyer")),
        FileField("status", "Status (void, refund ...)", False, ("state", "sale status", "type", "document type")),
        FileField("payment_method", "Payment method", False, ("payment", "paid by", "tender", "pay method",
                                                               "payment type", "mode of payment")),
        FileField("payment_reference", "Payment reference (transaction code)", False,
                  ("reference", "payment ref", "transaction code", "mpesa code", "txn ref", "ref no", "confirmation")),
        FileField("discount", "Discount (money)", False, ("discount amount", "total discount", "disc")),
        FileField("tax", "Tax", False, ("vat", "tax amount", "total tax")),
        FileField("entered_at", "Date it was entered (if the system keeps it)", False,
                  ("entry date", "date entered", "posted at", "recorded at", "created on", "system date")),
        FileField("product", "Item (for one row per item)", False, ("item", "item name", "product name", "description",
                                                                     "sku", "item code")),
        FileField("quantity", "Quantity", False, ("qty", "units")),
        FileField("unit_price", "Unit price", False, ("price", "rate", "selling price")),
        FileField("list_price", "Normal price", False, ("list price", "standard price", "original price")),
    )

    def records(self, rows: list[ParsedRow], reader: RowReader, account: str) -> dict[str, list[Record]]:
        groups: dict[str, list[ParsedRow]] = {}
        for row in rows:
            receipt = row.text("receipt")
            if not receipt:
                reader.issue(row, "receipt: a receipt or sale number is needed")
                continue
            groups.setdefault(receipt, []).append(row)
        sales: list[Record] = []
        for receipt, members in groups.items():
            sale = self._sale(receipt, members, reader)
            if sale is not None:
                sales.append(sale)
        return {"sales": sales}

    def _sale(self, receipt: str, members: list[ParsedRow], reader: RowReader) -> Sale | None:
        first = members[0]
        when = reader.moment(first, "date", "time", required=True)
        if when is None:
            return None
        lines: list[SaleLine] = []
        line_total = ZERO
        for row in members:
            if row.text("product") or row.text("quantity"):
                quantity = reader.number(row, "quantity") or Decimal(1)
                price = reader.number(row, "unit_price")
                if price is None:
                    continue
                discount = reader.number(row, "discount") if len(members) > 1 else None
                lines.append(SaleLine(row.text("product") or None, quantity, price, discount or ZERO,
                                      reader.number(row, "list_price")))
                line_total += quantity * price - (discount or ZERO)
        total = reader.number(first, "total")
        if total is None:
            if first.text("total"):
                return None                                  # the value was not a number: already reported
            if not lines:
                reader.issue(first, "total: the sale has no total and no items")
                return None
            total = line_total
        method = method_of(first.text("payment_method")) if first.text("payment_method") else None
        payments = (SalePayment(method, total, first.text("payment_reference") or None),) if method else ()
        discount_total = (reader.number(first, "discount") if len(members) == 1
                          else sum((line.discount for line in lines), ZERO))
        entered = reader.moment(first, "entered_at")
        return Sale(
            ref=receipt, occurred_at=when, total=abs(total), status=_status_of(first.text("status")),
            number=receipt, branch_ref=first.text("branch") or None, cashier_ref=first.text("cashier") or None,
            customer_ref=first.text("customer") or None, tax_total=reader.number(first, "tax") or ZERO,
            discount_total=discount_total or ZERO, lines=tuple(lines), payments=payments, entered_at=entered)


class CsvInvoices(FileConnector):
    kind = "csv_invoices"
    title = "Invoices and bills export"
    description = ("A spreadsheet of customer invoices or supplier bills with who, how much, when due, and how much "
                   "is paid.")
    entities = ("invoices", "parties")
    how_to = ("In your accounting or ERP system, export the list of invoices (or bills) as a CSV file with the number, "
              "customer or supplier, dates, total and amount paid or outstanding. Upload one file for customer "
              "invoices and another connection for supplier bills, or one file with a 'type' column.")
    fields = (
        FileField("number", "Invoice number", True, ("invoice no", "invoice number", "bill no", "document no", "doc no",
                                                      "reference", "id"), example="INV-0042"),
        FileField("kind", "Customer invoice or supplier bill", False, ("type", "document type", "invoice type"),
                  help="customer / supplier (or sales / purchase). Leave unmapped to use the option below."),
        FileField("party", "Customer or supplier", True, ("customer", "supplier", "vendor", "client", "name",
                                                           "customer name", "supplier name", "party")),
        FileField("issue_date", "Invoice date", True, ("date", "invoice date", "issued", "posting date", "bill date")),
        FileField("due_date", "Due date", False, ("due", "payment due", "due on")),
        FileField("total", "Total", True, ("amount", "grand total", "invoice total", "total amount", "gross")),
        FileField("paid", "Amount paid", False, ("paid amount", "amount paid", "received", "settled")),
        FileField("balance", "Balance outstanding", False, ("outstanding", "balance due", "amount due", "open amount",
                                                            "unpaid", "balance")),
        FileField("status", "Status", False, ("state", "invoice status")),
        FileField("branch", "Branch", False, ("store", "outlet", "location")),
        FileField("created_by", "Created by", False, ("user", "entered by", "prepared by")),
        FileField("approved_by", "Approved by", False, ("authorised by", "authorized by", "posted by")),
    )
    options_help = {"default_kind": "customer or supplier: used when the file has no type column"}

    def records(self, rows: list[ParsedRow], reader: RowReader, account: str) -> dict[str, list[Record]]:
        default_kind = str(reader.settings.options.get("default_kind", "customer"))
        invoices: list[Record] = []
        parties: dict[str, Party] = {}
        for row in rows:
            number = row.text("number")
            total = reader.number(row, "total", required=True)
            issued = reader.day(row, "issue_date", required=True)
            if not number:
                reader.issue(row, "number: an invoice number is needed")
            if not number or total is None or issued is None:
                continue
            word = (row.text("kind") or default_kind).lower()
            is_supplier = any(w in word for w in ("supplier", "vendor", "purchase", "bill", "payable"))
            kind: Literal["customer", "supplier"] = "supplier" if is_supplier else "customer"
            paid = reader.number(row, "paid")
            balance = reader.number(row, "balance")
            if paid is None:
                paid = total - balance if balance is not None else ZERO
            status_word = row.text("status").lower()
            status: Literal["open", "paid", "cancelled", "draft"]
            if any(w in status_word for w in ("cancel", "void")):
                status = "cancelled"
            elif "draft" in status_word:
                status = "draft"
            elif (paid >= total and total > 0) or ("paid" in status_word and "unpaid" not in status_word):
                status = "paid"
            else:
                status = "open"
            party_name = row.text("party")
            party_ref = _slug(party_name) if party_name else None
            if party_ref:
                parties.setdefault(f"{kind}:{party_ref}", Party(f"{kind}:{party_ref}", kind, party_name))
            invoices.append(Invoice(
                ref=f"{kind}:{number}", kind=kind, issue_date=issued, total=total, paid=paid,
                due_date=reader.day(row, "due_date"), number=number,
                party_ref=f"{kind}:{party_ref}" if party_ref else None, branch_ref=row.text("branch") or None,
                status=status,
                created_by_ref=row.text("created_by") or None, approved_by_ref=row.text("approved_by") or None))
        return {"invoices": invoices, "parties": list(parties.values())}


class CsvStock(FileConnector):
    kind = "csv_stock"
    title = "Stock movements export"
    description = "A spreadsheet of stock movements: what came in, went out or was adjusted, where and by whom."
    entities = ("stock_movements", "products")
    how_to = ("In your inventory or ERP system, export the stock movements (stock ledger) as a CSV file with the date, "
              "item, quantity in or out, type of movement, branch and user. Upload it here; newer exports can overlap "
              "older ones.")
    fields = (
        FileField("date", "Date (and time)", True, ("posting date", "movement date", "timestamp", "datetime")),
        FileField("time", "Time (if separate)", False, ("posting time",)),
        FileField("product", "Item", True, ("item", "item name", "product name", "sku", "item code", "description",
                                             "product")),
        FileField("quantity", "Quantity (+ in, - out)", False, ("qty", "actual qty", "quantity change", "change")),
        FileField("quantity_in", "Quantity in", False, ("in", "received", "qty in", "in qty", "stock in")),
        FileField("quantity_out", "Quantity out", False, ("out", "issued", "qty out", "out qty", "stock out")),
        FileField("kind", "Type of movement", False, ("type", "movement type", "voucher type", "transaction type",
                                                       "reason")),
        FileField("branch", "Branch or warehouse", False, ("warehouse", "store", "location", "site", "outlet")),
        FileField("user", "User", False, ("created by", "entered by", "owner", "operator")),
        FileField("reason", "Reason or note", False, ("remarks", "note", "notes", "comment", "narration")),
        FileField("unit_cost", "Unit cost", False, ("cost", "valuation rate", "rate", "cost price", "incoming rate")),
        FileField("entered_at", "Date it was entered", False, ("entry date", "creation", "recorded at", "created on")),
        FileField("number", "Movement number (makes re-uploads safe)", False, ("voucher no", "document no", "id",
            "ref")),
    )

    def records(self, rows: list[ParsedRow], reader: RowReader, account: str) -> dict[str, list[Record]]:
        movements: list[Record] = []
        products: dict[str, Product] = {}
        for row in rows:
            when = reader.moment(row, "date", "time", required=True)
            product = row.text("product")
            if not product:
                reader.issue(row, "product: an item is needed")
            quantity = reader.number(row, "quantity")
            if quantity is None:
                q_in, q_out = reader.number(row, "quantity_in"), reader.number(row, "quantity_out")
                if q_in is None and q_out is None:
                    reader.issue(row, "quantity: a quantity (or in and out columns) is needed")
                else:
                    quantity = (q_in or ZERO) - (q_out or ZERO)
            if when is None or not product or quantity is None:
                continue
            kind = self._kind(row.text("kind"), quantity)
            ref = row.text("number") or reader.unique(stable_ref(
                when.isoformat(), product, quantity, row.text("branch"), kind, row.text("reason")))
            products.setdefault(product, Product(ref=_slug(product), name=product))
            movements.append(StockMovement(
                ref=ref, occurred_at=when, product_ref=_slug(product), quantity=quantity, kind=kind,
                branch_ref=row.text("branch") or None, user_ref=row.text("user") or None,
                reason=row.text("reason") or None, unit_cost=reader.number(row, "unit_cost"),
                entered_at=reader.moment(row, "entered_at")))
        return {"stock_movements": movements, "products": list(products.values())}

    @staticmethod
    def _kind(word: str, quantity: Decimal) -> StockKind:
        low = word.lower()
        for kind, words in KIND_WORDS:
            if any(w in low for w in words):
                return kind
        return "other"


class CsvExpenses(FileConnector):
    kind = "csv_expenses"
    title = "Expenses export"
    description = "A spreadsheet of expenses with date, amount, category and who spent it."
    entities = ("expenses",)
    how_to = ("Export your expenses (or the expense accounts' transactions) from your system as a CSV file with the "
              "date, amount, category and description. Upload it here; newer exports can overlap older ones.")
    fields = (
        FileField("date", "Date", True, ("expense date", "posting date", "transaction date", "paid on")),
        FileField("amount", "Amount", True, ("expense amount", "total", "cost", "value", "debit")),
        FileField("category", "Category or account", False, ("expense account", "account", "type", "expense type",
                                                              "head", "ledger")),
        FileField("description", "Description", False, ("details", "narration", "note", "memo", "particulars")),
        FileField("branch", "Branch", False, ("store", "outlet", "location", "cost centre", "cost center")),
        FileField("user", "Spent or entered by", False, ("employee", "created by", "entered by", "paid by",
            "claimed by")),
        FileField("supplier", "Paid to", False, ("vendor", "payee", "supplier name")),
        FileField("number", "Expense number (makes re-uploads safe)", False, ("voucher no", "expense no", "id", "ref",
                                                                              "reference")),
    )

    def records(self, rows: list[ParsedRow], reader: RowReader, account: str) -> dict[str, list[Record]]:
        expenses: list[Record] = []
        for row in rows:
            when = reader.moment(row, "date", required=True)
            amount = reader.number(row, "amount", required=True)
            if when is None or amount is None:
                continue
            ref = row.text("number") or reader.unique(stable_ref(
                when.isoformat(), amount, row.text("category"), row.text("description"), row.text("branch")))
            expenses.append(Expense(
                ref=ref, occurred_at=when, amount=amount, category=row.text("category") or None,
                description=row.text("description") or None, branch_ref=row.text("branch") or None,
                user_ref=row.text("user") or None, party_ref=row.text("supplier") or None))
        return {"expenses": expenses}
