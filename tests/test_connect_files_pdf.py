"""Statements in every format a person might have: PDF (text, ruled, wrapped, three pages, protected, no header),
Excel and CSV, plus pictures read by a (fake) OCR engine. The layout is worked out with no settings chosen, and every
layout must arrive at the same transactions, totals and references (so mixing formats adds nothing twice)."""

from decimal import Decimal as D  # noqa: N817

import pytest

from tests import connect_file_fixtures as F  # noqa: N812
from tests.connect_helpers import CONNECT, make_connect_shop, new_connection, rows
from ziira.kernel import jobs
from ziira.modules.connect.public import OcrEngine, OcrWord
from ziira.modules.connect.services import scans


@pytest.fixture(scope="module")
def shop(client, registry):  # type: ignore[no-untyped-def]
    return make_connect_shop(client, registry, "Pdf Files Co")


def upload(client, shop, cid, data: bytes, mode: str = "preview", name: str = "statement.pdf",  # type: ignore[no-untyped-def]
           password: str | None = None, scan_id: str | None = None):
    headers = dict(shop["owner"])
    if password:
        headers["X-File-Password"] = password
    params = {"mode": mode, "filename": name}
    if scan_id:
        params["scan_id"] = scan_id
    return client.post(f"{CONNECT}/connections/{cid}/upload", headers=headers, content=data, params=params)


def payments(shop, cid):  # type: ignore[no-untyped-def]
    return rows(shop, "select * from connect.src_payment where connection_id = :c order by occurred_at, amount", c=cid)


LAYOUTS = {
    "in_out_with_title_and_footer": (F.pdf_in_out, "mobile_money_statement"),
    "single_signed_column": (F.pdf_signed, "bank_statement"),
    "dr_cr_marker": (F.pdf_dr_cr, "bank_statement"),
    "wrapped_descriptions": (F.pdf_wrapped, "bank_statement"),
    "three_pages_repeated_headers": (F.pdf_three_pages, "bank_statement"),
    "ruled_table": (F.pdf_ruled, "bank_statement"),
    "no_column_names_at_all": (F.pdf_no_header, "bank_statement"),
    "excel_with_title_block_and_totals": (F.xlsx_in_out, "mobile_money_statement"),
    "csv": (F.csv_in_out, "mobile_money_statement"),
}


@pytest.mark.parametrize("name", list(LAYOUTS))
def test_every_layout_gives_the_same_six_transactions_with_nothing_chosen(client, shop, name) -> None:  # type: ignore[no-untyped-def]
    make, kind = LAYOUTS[name]
    cid = new_connection(client, shop, kind, f"Layout {name}")["id"]
    shown = upload(client, shop, cid, make()).json()["preview"]
    assert shown["state"] == "ready" and shown["missing"] == [], shown["warnings"]
    assert shown["total_rows"] == 6 and shown["valid_rows"] == 6 and shown["issue_count"] == 0
    assert D(shown["money_in"]) == F.MONEY_IN and D(shown["money_out"]) == F.MONEY_OUT
    assert shown["confidence"] >= 0.8 and shown["needs_check"] is False, shown["check_reasons"]
    assert shown["first_moment"].startswith("2026-10-13") and shown["last_moment"].startswith("2026-10-17")
    done = upload(client, shop, cid, make(), "commit").json()
    assert done["committed"] and done["new"] == 6 and done["skipped"] == 0
    got = payments(shop, cid)
    assert [(p.direction, p.amount) for p in got] == [("in" if t.amount > 0 else "out", abs(t.amount))
                                                      for t in F.TRANSACTIONS]
    assert got[0].method == ("mobile_money" if kind == "mobile_money_statement" else "bank")
    assert upload(client, shop, cid, make(), "commit").json()["new"] == 0           # the same file again: nothing twice


def test_wrapped_lines_are_joined_and_titles_and_footers_are_skipped(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "bank_statement", "Wrapped detail")["id"]
    shown = upload(client, shop, cid, F.pdf_wrapped()).json()["preview"]
    assert any("2 wrapped line(s)" in w for w in shown["warnings"])
    upload(client, shop, cid, F.pdf_wrapped(), "commit")
    first = payments(shop, cid)[0]
    assert first.party_name == "Customer Payment from JANE W reference 7781 settled by till 3"
    three = new_connection(client, shop, "bank_statement", "Three pages")["id"]
    shown = upload(client, shop, three, F.pdf_three_pages()).json()["preview"]
    assert any("not transactions" in w for w in shown["warnings"]) and shown["total_rows"] == 6   # opening balance + 3 footers


def test_the_same_statement_in_pdf_excel_and_csv_adds_nothing_twice(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "mobile_money_statement", "All formats")["id"]
    assert upload(client, shop, cid, F.csv_in_out(), "commit", "s.csv").json()["new"] == 6
    assert upload(client, shop, cid, F.pdf_in_out(), "commit").json()["new"] == 0
    assert upload(client, shop, cid, F.xlsx_in_out(), "commit", "s.xlsx").json()["new"] == 0
    assert len(payments(shop, cid)) == 6


def test_a_protected_pdf_asks_for_its_password_which_is_used_once_and_never_kept(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "mobile_money_statement", "Protected")["id"]
    data = F.pdf_in_out(password="s3cret-pw")
    asked = upload(client, shop, cid, data).json()["preview"]
    assert asked["state"] == "password_required" and "password" in asked["message"]
    wrong = upload(client, shop, cid, data, password="nope").json()["preview"]
    assert wrong["state"] == "wrong_password"
    right = upload(client, shop, cid, data, password="s3cret-pw").json()["preview"]
    assert right["state"] == "ready" and right["valid_rows"] == 6
    done = upload(client, shop, cid, data, "commit", password="s3cret-pw").json()
    assert done["new"] == 6
    stored = rows(shop, "select config::text as c from connect.connection where id = :c", c=cid)[0].c
    assert "s3cret-pw" not in stored
    audit = rows(shop, "select changes::text as d from kernel.audit_log where entity_id = :c", c=cid)
    assert all("s3cret-pw" not in (a.d or "") for a in audit)
    refused = upload(client, shop, cid, data, "commit")
    assert refused.status_code == 422 and "password" in refused.text


def test_ambiguous_dates_are_not_guessed_silently_and_the_choice_is_remembered(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "bank_statement", "Ambiguous dates")["id"]
    csv = b"Date,Details,Amount\n03/04/2026,Rent,-500.00\n05/04/2026,Sale,900.00\n"
    shown = upload(client, shop, cid, csv, name="s.csv").json()["preview"]
    assert shown["date_ambiguous"] is True and "dates" in shown["check_reasons"] and shown["needs_check"]
    assert shown["date_examples"] == ["03/04/2026", "05/04/2026"]
    client.put(f"{CONNECT}/connections/{cid}/file-settings", headers=shop["owner"],
               json={"mapping": {}, "date_format": "mdy", "decimal_separator": "."})
    again = upload(client, shop, cid, csv, name="s.csv").json()["preview"]
    assert again["date_ambiguous"] is False and again["first_moment"].startswith("2026-03-04")
    clear = new_connection(client, shop, "bank_statement", "Clear dates")["id"]
    assert upload(client, shop, clear, b"Date,Details,Amount\n13/04/2026,Rent,-500.00\n", name="s.csv").json()[
        "preview"]["date_ambiguous"] is False


def test_the_first_confirmed_upload_is_remembered_so_the_next_needs_no_checking(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "bank_statement", "Remembered")["id"]
    csv = b"Date;Details;Amount\n03/04/2026;Rent;-1.500,50\n05/04/2026;Sale;900,00\n"
    first = upload(client, shop, cid, csv, name="s.csv").json()["preview"]
    assert first["settings"]["decimal_separator"] == "," and first["date_ambiguous"] is True
    upload(client, shop, cid, csv, "commit", name="s.csv")
    nxt = upload(client, shop, cid, b"Date;Details;Amount\n06/04/2026;Fuel;-20,00\n", name="n.csv").json()["preview"]
    assert nxt["settings"]["remembered"] is True and nxt["date_ambiguous"] is False and nxt["needs_check"] is False
    assert D(nxt["money_out"]) == D("20.00")


def test_a_file_of_the_wrong_kind_says_so_and_suggests_the_right_one(client, shop) -> None:  # type: ignore[no-untyped-def]
    sales = (b"Receipt No,Sale Date,Store,Served By,Payment,Amount\nR-1,2026-10-14,Head office,Achieng,Cash,1250.00\n"
             b"R-2,2026-10-14,Juja,Wambui,Cash,300.00\n")
    bank = new_connection(client, shop, "bank_statement", "Wrong kind bank")["id"]
    shown = upload(client, shop, bank, sales, name="sales.csv").json()["preview"]
    assert shown["wrong_kind"] == {"kind": "csv_sales", "title": "Sales export"} and "wrong_kind" in shown["check_reasons"]
    till = new_connection(client, shop, "csv_sales", "Wrong kind till")["id"]
    shown = upload(client, shop, till, F.csv_in_out(), name="s.csv").json()["preview"]
    assert shown["wrong_kind"]["kind"] in ("mobile_money_statement", "bank_statement")
    ok = upload(client, shop, till, sales, name="sales.csv").json()["preview"]
    assert ok["wrong_kind"] is None


def test_dropping_a_file_names_its_kind(client, shop) -> None:  # type: ignore[no-untyped-def]
    def detect(data: bytes, password: str | None = None) -> dict:  # type: ignore[type-arg]
        headers = dict(shop["owner"])
        if password:
            headers["X-File-Password"] = password
        r = client.post(f"{CONNECT}/files/detect", headers=headers, content=data)
        assert r.status_code == 200, r.text
        return r.json()

    assert detect(F.pdf_in_out())["kind"] == "mobile_money_statement"
    assert detect(F.pdf_signed())["kind"] == "bank_statement"
    assert detect(F.xlsx_in_out())["kind"] == "mobile_money_statement"
    assert detect(F.pdf_in_out(password="pw-9"), "pw-9")["kind"] == "mobile_money_statement"
    sales = b"Receipt No,Sale Date,Store,Served By,Payment,Amount\nR-1,2026-10-14,Head office,Achieng,Cash,1250.00\n"
    assert detect(sales)["kind"] == "csv_sales"
    stock = b"Date,Item,In,Out,Type,Warehouse\n2026-10-01,Cement,100,,Purchase receipt,Head office\n"
    assert detect(stock)["kind"] == "csv_stock"
    header, xs, table = F.scan_rows()
    assert detect(F.png_bytes(F.render_page(table, header, xs)))["picture"] is True
    protected = client.post(f"{CONNECT}/files/detect", headers=shop["owner"], content=F.pdf_in_out(password="pw-9"))
    assert protected.status_code == 200 and protected.json()["state"] == "password_required"
    assert protected.json()["kind"] is None


def test_unreadable_and_unsupported_files_say_what_to_do(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "bank_statement", "Bad files")["id"]
    old = upload(client, shop, cid, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 100, name="old.xls")
    assert old.status_code == 422 and ".xlsx" in old.text
    broken = upload(client, shop, cid, b"%PDF-1.4 this is not really a pdf")
    assert broken.status_code == 422 and "could not be read" in broken.text
    nothing = upload(client, shop, cid, F.draw_pdf([F.Col("Colour", 50)], [["red apples and blue pears on the table"]] * 8))
    assert nothing.status_code == 422 and "No transactions" in nothing.text
    header, xs, table = F.scan_rows()
    picture = upload(client, shop, cid, F.pdf_of_image(F.render_page(table, header, xs)))
    assert picture.status_code == 422 and "not switched on" in picture.text


def test_problem_lines_are_listed_in_plain_words_with_their_content(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "bank_statement", "Problems")["id"]
    csv = (b"Date,Details,Amount\n2026-10-14,Rent,-500.00\n2026-10-15,Odd amount,twelve\n"
           b"31/02/2026,Impossible day,5.00\n2026-10-16,Fine,20.00\n")
    shown = upload(client, shop, cid, csv, name="p.csv").json()["preview"]
    assert shown["valid_rows"] == 2 and shown["issue_count"] == 2 and "problems" in shown["check_reasons"]
    assert {r["row"] for r in shown["review_rows"]} == {3, 4}
    assert shown["review_rows"][0]["cells"] == ["2026-10-15", "Odd amount", "twelve"]
    done = upload(client, shop, cid, csv, "commit", name="p.csv").json()
    assert done["new"] == 2 and done["skipped"] == 2


# --------------------------------------------------------------------------- pictures, with a made-up OCR engine
class FakeEngine(OcrEngine):
    """Reads the words of the statement fixture exactly (with an optional misread digit): a stand-in for Tesseract."""

    name = "fake"
    words: list[OcrWord] = []

    def unavailable(self) -> str | None:
        return None

    def read(self, image_png: bytes) -> list[OcrWord]:
        return list(FakeEngine.words)


def words_of(rows: list[list[str]], header: list[str], xs: list[int], *, doubt: set[tuple[int, int]] = frozenset()  # type: ignore[assignment]
             ) -> list[OcrWord]:
    out = []
    for r, line in enumerate([header, *rows]):
        for c, (x, cell) in enumerate(zip(xs, line, strict=True)):
            if cell:
                left = x
                for token in cell.split(" "):
                    out.append(OcrWord(token, left, 100 + r * 44, left + 12 * len(token), 122 + r * 44,
                                       40.0 if (r - 1, c) in doubt else 96.0))
                    left += 12 * len(token) + 8
    return out


@pytest.fixture
def reader(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(scans, "engine", lambda session: FakeEngine())
    monkeypatch.setattr(scans, "why_unavailable", lambda session: None)
    return FakeEngine


def scan_upload(client, shop, cid, data: bytes, name: str):  # type: ignore[no-untyped-def]
    asked = upload(client, shop, cid, data, name=name).json()["preview"]
    assert asked["state"] == "reading" and asked["scan"]["status"] == "queued", asked
    jobs.run_due(shop["tenant_id"])
    scan = client.get(f"{CONNECT}/connections/{cid}/scans/{asked['scan']['id']}", headers=shop["owner"]).json()
    return asked["scan"]["id"], scan


def test_a_scanned_pdf_is_read_in_the_background_checked_by_its_balance_and_corrected_before_confirming(  # type: ignore[no-untyped-def]
        client, shop, reader) -> None:
    header, xs, table = F.scan_rows()
    misread = [list(r) for r in table]
    misread[2][4] = "9,600.50"                                  # a 8 read as a 6 in the balance of the third line
    reader.words = words_of(misread, header, xs)
    cid = new_connection(client, shop, "bank_statement", "Scanned statement")["id"]
    scan_id, scan = scan_upload(client, shop, cid, F.pdf_of_image(F.render_page(table, header, xs, tilt=1.5, noise=True)),
                                "scan.pdf")
    assert scan["status"] == "ready" and scan["pages"] == 1 and scan["pages_done"] == 1
    shown = upload(client, shop, cid, b"", scan_id=scan_id).json()["preview"]
    assert shown["state"] == "ready" and shown["source"] == "scan" and shown["total_rows"] == 6
    assert shown["needs_check"] and "picture" in shown["check_reasons"]
    flagged = {r["row"]: r["problem"] for r in shown["review_rows"]}
    assert len(flagged) == 2 and all("balance does not add up" in p for p in flagged.values())   # lines 3 and 4 follow from it
    assert shown["valid_rows"] == 4
    committed_early = upload(client, shop, cid, b"", "commit", scan_id=scan_id).json()
    assert committed_early["new"] == 4                                                       # misread lines were left out
    cid2 = new_connection(client, shop, "bank_statement", "Scanned statement fixed")["id"]
    reader.words = words_of(misread, header, xs)
    scan_id, _ = scan_upload(client, shop, cid2, F.pdf_of_image(F.render_page(table, header, xs)), "scan.pdf")
    review = upload(client, shop, cid2, b"", scan_id=scan_id).json()["preview"]["review_rows"]
    balance_column = header.index("Balance")
    third = next(r for r in review if r["cells"][balance_column] == "9,600.50")
    fix = client.patch(f"{CONNECT}/connections/{cid2}/scans/{scan_id}", headers=shop["owner"],
                       json={"fixes": [{"row": third["row"], "column": balance_column, "value": "9,800.50"}]})
    assert fix.status_code == 204, fix.text
    fixed = upload(client, shop, cid2, b"", scan_id=scan_id).json()["preview"]
    assert fixed["valid_rows"] == 6 and fixed["issue_count"] == 0 and fixed["needs_check"]       # still asks to confirm
    assert D(fixed["money_in"]) == F.MONEY_IN and D(fixed["money_out"]) == F.MONEY_OUT
    assert upload(client, shop, cid2, b"", "commit", scan_id=scan_id).json()["new"] == 6
    assert rows(shop, "select count(*) as n from connect.scan where connection_id = :c", c=cid2)[0].n == 0
    assert upload(client, shop, cid2, b"", scan_id=scan_id).status_code == 404            # confirmed: nothing left


def test_a_doubtful_word_is_flagged_even_when_there_is_no_balance_to_check_it_against(client, shop, reader) -> None:  # type: ignore[no-untyped-def]
    header = ["Date", "Details", "Amount"]
    xs = [30, 190, 640]
    table = [[F.dmy(t.day), t.details, ("-" if t.amount < 0 else "") + F.money(abs(t.amount))] for t in F.TRANSACTIONS]
    reader.words = words_of(table, header, xs, doubt={(1, 2)})
    cid = new_connection(client, shop, "bank_statement", "Photo no balance")["id"]
    photo = F.png_bytes(F.render_page(table, header, xs, tilt=-1.0, noise=True), "JPEG")
    scan_id, _ = scan_upload(client, shop, cid, photo, "photo.jpg")
    shown = upload(client, shop, cid, b"", scan_id=scan_id).json()["preview"]
    assert shown["valid_rows"] == 5 and "hard to read" in shown["review_rows"][0]["problem"]


def test_pictures_are_refused_clearly_when_the_server_cannot_read_them(client, shop) -> None:  # type: ignore[no-untyped-def]
    cid = new_connection(client, shop, "bank_statement", "No reader")["id"]
    header, xs, table = F.scan_rows()
    r = upload(client, shop, cid, F.png_bytes(F.render_page(table, header, xs)), name="photo.png")
    status = client.get(f"{CONNECT}/ocr", headers=shop["owner"]).json()
    if status["available"]:
        pytest.skip("this machine can read pictures")
    assert r.status_code == 422 and "not switched on" in r.text and "tesseract" in status["message"].lower()
