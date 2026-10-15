"""Registers the API connectors (ERPNext, Odoo, Zoho Books, QuickBooks Online) with the `connect.connector` socket.

Each class registers itself with `@provides("connect.connector")` when its module is imported; the unit's `hooks.py`
imports this module so all four are loaded. Add a new API connector by importing it here.
"""

from ziira.modules.connect.connectors.erpnext import ErpNextConnector
from ziira.modules.connect.connectors.odoo import OdooConnector
from ziira.modules.connect.connectors.quickbooks import QuickBooksConnector
from ziira.modules.connect.connectors.zoho_books import ZohoBooksConnector

API_CONNECTORS = (ErpNextConnector, OdooConnector, ZohoBooksConnector, QuickBooksConnector)
