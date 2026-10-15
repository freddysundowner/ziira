"""Registers the file and statement connectors with the `connect.connector` socket (imported by hooks.py)."""

from ziira.modules.connect.connectors.csv_exports import CsvExpenses, CsvInvoices, CsvSales, CsvStock
from ziira.modules.connect.connectors.statements import BankStatement, MobileMoneyStatement
from ziira.modules.connect.public import CONNECTOR
from ziira.sdk import provides

FILE_CONNECTORS = (CsvSales, CsvInvoices, CsvStock, CsvExpenses, BankStatement, MobileMoneyStatement)
for _connector in FILE_CONNECTORS:
    provides(CONNECTOR)(_connector)
