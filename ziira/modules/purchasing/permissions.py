"""Permission codes of the Purchasing and Suppliers module (declared in manifest.toml)."""

SUPPLIERS_MANAGE = "suppliers.manage"
SUPPLIER_BANK_EDIT = "supplier.bank_edit"
SUPPLIER_BANK_CONFIRM = "supplier.bank_confirm"
PO_CREATE = "po.create"
PO_APPROVE = "po.approve"
GOODS_RECEIVE = "goods.receive"
BILLS_MANAGE = "bills.manage"
BILLS_APPROVE = "bills.approve"
BILLS_PAY = "bills.pay"
PURCHASING_VIEW = "purchasing.view"

ALL = (SUPPLIERS_MANAGE, SUPPLIER_BANK_EDIT, SUPPLIER_BANK_CONFIRM, PO_CREATE, PO_APPROVE, GOODS_RECEIVE, BILLS_MANAGE,
       BILLS_APPROVE, BILLS_PAY, PURCHASING_VIEW)
