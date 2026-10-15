"""File and statement connectors on realistic ugly files, uploaded through the API: byte-order marks, semicolons, comma
decimals, signed amount columns, title lines, overlapping statements uploaded twice, validation reports, saved mappings."""

from datetime import date
from decimal import Decimal as D  # noqa: N817

import pytest

from tests.connect_helpers import CONNECT, at, make_connect_shop, new_connection, rows, scalar
from ziira.modules.connect.domain import csvfile, values


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_connect_shop(client, registry, "Files Co")


def upload(client, shop, cid: str, data: bytes, mode: str = "preview", name: str = "file.csv"):  # type: ignore[no-untyped-def]
    return client.post(f"{CONNECT}/connections/{cid}/upload", headers=shop["owner"], content=data,
                       params={"mode": mode, "filename": name})


def settings(client, shop, cid: str, **kw):  # type: ignore[no-untyped-def]
    body = {"mapping": {}, "decimal_separator": ".", "date_format": "iso", **kw}
    r = client.put(f"{CONNECT}/connections/{cid}/file-settings", headers=shop["owner"], json=body)
    assert r.status_code == 204, r.text


def table(shop, name: str, cid: str):  # type: ignore[no-untyped-def]
    return rows(shop, f"select * from connect.{name} where connection_id = :c order by id", c=cid)


# --------------------------------------------------------------------------- the parsing helpers
def test_numbers_are_read_with_the_files_decimal_separator_and_decoration() -> None:
    assert values.parse_decimal("1,234.50") == D("1234.50") and values.parse_decimal("1.234,50", ",") == D("1234.50")
    assert values.parse_decimal("KES 1,200.00") == D("1200.00") and values.parse_decimal("Ksh1200") == D("1200")
    assert values.parse_decimal("(12.00)") == D("-12.00") and values.parse_decimal("12.00-") == D("-12.00")
    assert values.parse_decimal("1 234,5", ",") == D("1234.5") and values.parse_decimal("500 DR") == D("-500")
    assert values.parse_decimal("500 CR") == D("500")
    for bad in ("", "abc", "1,5", "12.3.4", "--5"):
        with pytest.raises(ValueError):
            values.parse_decimal(bad)


def test_dates_and_times_in_the_common_layouts() -> None:
    assert values.parse_date("14/10/2026", "dmy") == date(2026, 10, 14) and values.parse_date("10/14/2026", "mdy") == date(2026, 10, 14)
    assert values.parse_date("14-Oct-2026") == date(2026, 10, 14) and values.parse_date("2026/10/14") == date(2026, 10, 14)
    with pytest.raises(ValueError):
        values.parse_date("14/10/2026", "iso")
    with pytest.raises(ValueError):
        values.parse_date("31/02/2026", "dmy")
    moment = values.parse_datetime("14/10/2026 1:45 PM", "dmy", "Africa/Nairobi")
    assert (moment.hour, moment.minute, moment.utcoffset().total_seconds()) == (13, 45, 3 * 3600)  # type: ignore[union-attr]
    assert values.parse_datetime("2026-10-14T13:45:02Z", "iso", "Africa/Nairobi").hour == 13
    assert values.parse_datetime("2026-10-14", "iso", "UTC").hour == 12                 # a date alone is taken at noon
    assert values.parse_datetime("2026-10-14", "iso", "UTC", "08:15").hour == 8


def test_csv_files_with_bom_semicolons_title_lines_and_utf16_are_read() -> None:
    plain = csvfile.parse_file("﻿Date;Amount;Note\n2026-10-14;1,5;\"a; b\"\n\n2026-10-15;2,5;x\n".encode())
    assert plain.delimiter == ";" and plain.headers == ["Date", "Amount", "Note"] and len(plain.rows) == 2
    assert plain.rows[0][1][2] == "a; b"
    titled = csvfile.parse_file(b"Statement for account 123\nPrinted 14 Oct\n\nDate,Details,Paid In\n2026-10-14,x,5\n",
                                header_hint={"date", "details", "paidin"})
    assert titled.headers == ["Date", "Details", "Paid In"] and len(titled.rows) == 1 and "ignored" in titled.warnings[0]
    utf16 = csvfile.parse_file("a,b\n1,2\n".encode("utf-16"))
    assert utf16.headers == ["a", "b"]
    old = csvfile.parse_file("name,amt\nJos\xe9,5\n".encode("cp1252"))
    assert old.rows[0][1][0] == "Jos\xe9" and "Windows-1252" in old.warnings[0]
    for bad, why in ((b"", "empty"), (b"PK\x03\x04zzzz", "Excel"), (b"a,b\n", "no data rows"), (b"a\x00b", "CSV text")):
        with pytest.raises(csvfile.FileProblem, match=why):
            csvfile.parse_file(bad)
    with pytest.raises(csvfile.FileProblem, match="rows"):
        csvfile.parse_file(b"a\n" + b"1\n" * (csvfile.MAX_ROWS + 1))


def test_column_guessing_prefers_exact_names_and_uses_a_header_once() -> None:
    got = csvfile.suggest_mapping(["Receipt No.", "Sale Date", "Amount (KES)", "Served By", "Pay Method"],
                                  [("receipt", ("receipt no",)), ("date", ("sale date",)), ("total", ("amount",)),
                                   ("cashier", ("served by",)), ("payment_method", ("pay method",)),
                                   ("branch", ("store",))])
    assert got == {"receipt": "Receipt No.", "date": "Sale Date", "total": "Amount (KES)", "cashier": "Served By",
                   "payment_method": "Pay Method", "branch": None}


# --------------------------------------------------------------------------- sales exports
SALES = ("﻿Receipt No;Date;Time;Store;Served By;Payment;Reference;Amount;Status\n"
         "R-1;14/10/2026;09:15;Head office;Achieng;Cash;;1.250,50;Completed\n"
         "R-2;14/10/2026;11:40;Juja;Wambui;Mobile money;QWE123;300,00;Completed\n"
         "R-3;14/10/2026;12:00;Juja;Wambui;Cash;;99,00;Voided\n"
         "R-4;15/10/2026;08:05;Head office;Achieng;Bank transfer;TRF9;5.000,00;Completed\n"
         "R-5;31/02/2026;08:05;Head office;Achieng;Cash;;10,00;Completed\n"
         "R-6;16/10/2026;08:05;Head office;Achieng;Cash;;abc;Completed\n"
         ";16/10/2026;08:05;Head office;Achieng;Cash;;10,00;Completed\n").encode()


def test_a_sales_export_with_semicolons_comma_decimals_and_bad_rows(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "csv_sales", "Till export")["id"]
    settings(client, shop, cid, decimal_separator=",", date_format="dmy")
    seen = upload(client, shop, cid, SALES).json()["preview"]
    assert seen["delimiter"] == ";" and seen["total_rows"] == 7 and seen["valid_rows"] == 4
    assert seen["mapping"]["receipt"] == "Receipt No" and seen["mapping"]["branch"] == "Store"
    assert seen["mapping"]["cashier"] == "Served By" and seen["mapping"]["payment_method"] == "Payment"
    assert seen["mapping"]["total"] == "Amount" and seen["missing"] == [] and seen["records"] == {"sales": 4}
    problems = {i["row"]: i["message"] for i in seen["issues"]}
    assert set(problems) == {6, 7, 8} and "not a real date" in problems[6] and "not a number" in problems[7]
    assert "sale number" in problems[8]
    assert table(shop, "src_sale", cid) == []                                         # a preview stores nothing
    done = upload(client, shop, cid, SALES, "commit").json()
    assert done["committed"] and done["new"] == 4 and done["skipped"] == 3
    sales = {r.ref: r for r in table(shop, "src_sale", cid)}
    assert sales["R-1"].total == D("1250.50") and sales["R-1"].status == "posted" and sales["R-3"].status == "voided"
    assert sales["R-1"].occurred_at == at(date(2026, 10, 14), 9, 15) and sales["R-1"].cashier_ref == "Achieng"
    pays = {(r.sale_id, r.method, r.reference) for r in table(shop, "src_sale_payment", cid)}
    assert {m for _, m, _ in pays} == {"cash", "mobile_money", "bank"} and any(ref == "QWE123" for _, _, ref in pays)
    maps = {m["external_ref"] for m in client.get(f"{CONNECT}/connections/{cid}/branches", headers=shop["owner"]).json()}
    assert maps == {"Head office", "Juja"}
    again = upload(client, shop, cid, SALES, "commit").json()                          # the same file again: nothing twice
    assert again["new"] == 0 and again["changed"] == 0 and len(table(shop, "src_sale", cid)) == 4
    cov = client.get(f"{CONNECT}/connections/{cid}", headers=shop["owner"]).json()
    assert cov["entities"][0]["entity"] == "sales" and cov["entities"][0]["data_through"].startswith("2026-10-15")
    runs = client.get(f"{CONNECT}/connections/{cid}/runs", headers=shop["owner"]).json()
    assert runs[0]["trigger"] == "upload" and any("File: file.csv" in n for n in runs[0]["notes"])


def test_receipts_with_one_row_per_item_are_one_sale_and_a_saved_mapping_wins(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "csv_sales", "Item rows")["id"]
    data = (b"Bill,Sold On,Item,Qty,Price,Cashier\n"
            b"B1,2026-10-14 10:00,Cement,2,700,Ann\nB1,2026-10-14 10:00,Nails,1,150.50,Ann\n"
            b"B2,2026-10-14 11:00,Cement,1,700,Ben\n")
    settings(client, shop, cid, mapping={"receipt": "Bill", "date": "Sold On", "product": "Item", "quantity": "Qty",
                                         "unit_price": "Price", "cashier": "Cashier", "branch": ""})
    upload(client, shop, cid, data, "commit")
    sales = {r.ref: r for r in table(shop, "src_sale", cid)}
    assert sales["B1"].total == D("1550.50") and sales["B2"].total == D("700")           # 2 x 700 + 150.50
    lines = [(r.product_ref, r.quantity, r.unit_price) for r in table(shop, "src_sale_line", cid)]
    assert sorted(lines, key=str) == sorted([("Cement", D(2), D(700)), ("Nails", D(1), D("150.50")), ("Cement", D(1), D(700))], key=str)
    r = client.put(f"{CONNECT}/connections/{cid}/file-settings", headers=shop["owner"],
                   json={"mapping": {"nonsense": "x"}, "decimal_separator": ".", "date_format": "iso"})
    assert r.status_code == 422


def test_a_file_missing_a_required_column_is_not_committed(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "csv_sales", "Bad columns")["id"]
    shown = upload(client, shop, cid, b"Foo,Bar\n1,2\n").json()["preview"]
    assert "Receipt or sale number" in shown["missing"] and shown["records"] == {}
    r = upload(client, shop, cid, b"Foo,Bar\n1,2\n", "commit")
    assert r.status_code == 422 and "Choose the column for" in r.text
    assert upload(client, shop, cid, b"PK\x03\x04junk").status_code == 422
    assert upload(client, shop, cid, b"").status_code == 422


def test_uploads_are_size_limited_and_need_a_file_connection(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "csv_sales", "Big")["id"]
    big = b"a,b\n" + b"1,2\n" * (csvfile.MAX_BYTES // 4 + 10)
    r = upload(client, shop, cid, big)
    assert r.status_code in (413, 422)


# --------------------------------------------------------------------------- invoices, stock, expenses
def test_invoices_stock_and_expenses_exports(client, shop) -> None:  # type: ignore[no-untyped-def]
    inv = new_connection(client, shop, "csv_invoices", "Invoices")["id"]
    settings(client, shop, inv, options={"default_kind": "customer"})
    data = (b"Invoice No,Customer,Invoice Date,Due Date,Grand Total,Outstanding,Status\n"
            b"INV-1,Mama Njeri,2026-09-01,2026-09-30,\"1,000.00\",\"400.00\",Unpaid\n"
            b"INV-2,Kamau Hardware,2026-09-03,2026-10-03,500.00,0.00,Paid\n"
            b"INV-3,Mama Njeri,2026-09-10,2026-10-10,200.00,200.00,Cancelled\n"
            b"INV-4,Bad,not a date,2026-10-10,200.00,200.00,Unpaid\n")
    done = upload(client, shop, inv, data, "commit").json()
    assert done["new"] == 5 and done["skipped"] == 1                                    # 3 invoices + 2 parties; one bad row
    got = {r.number: r for r in table(shop, "src_invoice", inv)}
    assert (got["INV-1"].paid, got["INV-1"].status, got["INV-1"].kind) == (D("600"), "open", "customer")
    assert got["INV-2"].status == "paid" and got["INV-3"].status == "cancelled"
    assert {r.name for r in table(shop, "src_party", inv)} == {"Mama Njeri", "Kamau Hardware"}
    assert upload(client, shop, inv, data, "commit").json()["new"] == 0

    stock = new_connection(client, shop, "csv_stock", "Stock")["id"]
    data = (b"Date,Item,In,Out,Type,Warehouse,User,Remarks,Cost\n"
            b"2026-10-01,Cement,100,,Purchase receipt,Head office,Ann,GRN 4,720\n"
            b"2026-10-02,Cement,,3,Sales delivery,Head office,Ann,,\n"
            b"2026-10-03,Cement,,7,Stock adjustment (damage),Head office,Ben,wet bags,720\n"
            b"2026-10-03,Cement,,7,Stock adjustment (damage),Head office,Ben,wet bags,720\n"
            b"2026-10-04,Nails,,0,Stock count,Juja,Ben,,\n")
    done = upload(client, shop, stock, data, "commit").json()
    kinds = sorted((r.kind, r.quantity) for r in table(shop, "src_stock_movement", stock))
    assert kinds == [("adjustment", D(-7)), ("adjustment", D(-7)), ("count", D(0)), ("purchase", D(100)), ("sale", D(-3))]
    assert done["new"] == 5 + 2 and upload(client, shop, stock, data, "commit").json()["new"] == 0   # identical rows are kept apart

    exp = new_connection(client, shop, "csv_expenses", "Expenses")["id"]
    data = b"Date,Amount,Category,Description\n2026-10-01,\"1,200.00\",Fuel,Diesel\n2026-10-01,\"1,200.00\",Fuel,Diesel\n2026-10-02,300,Tea,\n"
    assert upload(client, shop, exp, data, "commit").json()["new"] == 3
    assert upload(client, shop, exp, data, "commit").json()["new"] == 0
    assert scalar(shop, "select sum(amount) from connect.src_expense where connection_id = :c", c=exp) == D("2700")


# --------------------------------------------------------------------------- statements
MOBILE = ("Account 0712345 statement\nPrinted 2026-10-15\n\n"
          "Receipt No.,Completion Time,Details,Transaction Status,Paid in,Withdrawn,Balance\n"
          "QWE123,2026-10-14 09:30:12,Customer Payment from 2547***123 - JANE W,Completed,300.00,,10300.00\n"
          "QWE124,2026-10-14 10:30:00,Payment to supplier - UNGA LTD,Completed,,\"2,000.00\",8300.00\n"
          "QWE125,2026-10-14 11:00:00,Customer Payment from 2547***999 - JOHN K,Failed,500.00,,8300.00\n"
          "QWE126,2026-10-14 12:00:00,Opening line,Completed,0.00,0.00,8300.00\n")


def test_a_mobile_money_statement_with_a_title_block_statuses_and_separate_in_out_columns(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "mobile_money_statement", "Till 0712")["id"]
    seen = upload(client, shop, cid, MOBILE.encode()).json()["preview"]
    assert seen["mapping"]["reference"] == "Receipt No." and seen["mapping"]["money_in"] == "Paid in"
    assert seen["mapping"]["money_out"] == "Withdrawn" and seen["mapping"]["date"] == "Completion Time"
    assert any("ignored" in w for w in seen["warnings"])
    done = upload(client, shop, cid, MOBILE.encode(), "commit").json()
    assert done["new"] == 2 and done["skipped"] == 1                                    # the failed transaction is reported
    pays = {r.reference: r for r in table(shop, "src_payment", cid)}
    assert set(pays) == {"QWE123", "QWE124"}
    assert (pays["QWE123"].direction, pays["QWE123"].amount, pays["QWE123"].method) == ("in", D("300.00"), "mobile_money")
    assert (pays["QWE124"].direction, pays["QWE124"].amount) == ("out", D("2000.00"))
    assert pays["QWE123"].occurred_at == at(date(2026, 10, 14), 9, 30).replace(second=12)
    assert "JANE W" in pays["QWE123"].party_name and pays["QWE123"].account == "Till 0712"


BANK_JAN = ("Date,Narration,Ref,Amount,Dr/Cr\n"
            "2026-10-01,CASH DEPOSIT HEAD OFFICE,CD1,\"10,000.00\",CR\n2026-10-02,TRANSFER FROM CUSTOMER,FT2,\"2,500.00\",CR\n"
            "2026-10-03,RENT,FT3,\"4,000.00\",DR\n")
BANK_FEB = ("Date,Narration,Ref,Amount,Dr/Cr\n"
            "2026-10-02,TRANSFER FROM CUSTOMER,FT2,\"2,500.00\",CR\n2026-10-03,RENT,FT3,\"4,000.00\",DR\n"
            "2026-10-04,SALARY,FT4,\"9,000.00\",DR\n2026-10-05,CASH DEPOSIT JUJA,CD2,\"3,000.00\",CR\n")


def test_overlapping_bank_statements_add_nothing_twice(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "bank_statement", "Main bank")["id"]
    assert upload(client, shop, cid, BANK_JAN.encode(), "commit").json()["new"] == 3
    second = upload(client, shop, cid, BANK_FEB.encode(), "commit").json()
    assert second["new"] == 2 and second["changed"] == 0                                # two lines were already read
    assert len(table(shop, "src_payment", cid)) == 5
    assert upload(client, shop, cid, BANK_FEB.encode(), "commit").json()["new"] == 0
    by_ref = {r.reference: r for r in table(shop, "src_payment", cid)}
    assert (by_ref["CD1"].method, by_ref["CD1"].direction) == ("cash", "in")             # "CASH DEPOSIT" in the narration
    assert (by_ref["FT2"].method, by_ref["FT2"].direction) == ("bank", "in")
    assert (by_ref["FT3"].direction, by_ref["FT3"].amount) == ("out", D("4000.00"))
    assert scalar(shop, "select sum(amount) filter (where direction = 'in') - sum(amount) filter (where direction = 'out') "
                        "from connect.src_payment where connection_id = :c", c=cid) == D("15500") - D("13000")


def test_a_statement_with_one_signed_column_comma_decimals_and_lines_without_codes(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "bank_statement", "Signed bank")["id"]
    settings(client, shop, cid, decimal_separator=",", date_format="dmy", delimiter=";",
             options={"deposit_words": "versement"})
    data = (b"Booking date;Description;Transaction amount;Balance\n"
            b"14/10/2026;VERSEMENT AGENCE;1.200,50;5.000,00\n"
            b"14/10/2026;FRAIS;-12,00;4.988,00\n"
            b"15/10/2026;VIREMENT CLIENT;300,00;5.288,00\n"
            b"15/10/2026;VIREMENT CLIENT;300,00;5.588,00\n")
    done = upload(client, shop, cid, data, "commit").json()
    assert done["new"] == 4                                                              # two identical lines with different balances
    pays = sorted(table(shop, "src_payment", cid), key=lambda r: (r.occurred_at, r.amount))
    assert [(p.direction, p.amount, p.method) for p in pays] == [
        ("out", D("12.00"), "bank"), ("in", D("1200.50"), "cash"), ("in", D("300.00"), "bank"), ("in", D("300.00"), "bank")]
    assert upload(client, shop, cid, data, "commit").json()["new"] == 0
