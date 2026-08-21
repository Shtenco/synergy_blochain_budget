from io import BytesIO
from zipfile import ZipFile

import openpyxl

from synergy_budget.kbk import ExpenseKBK
from synergy_budget.tabular import iter_archive_tables, money_to_kopecks
from synergy_budget.treasury import parse_table
from synergy_budget.reconcile import reconcile
from synergy_budget.graph import build_flow_graph
from synergy_budget.eis import parse_contract_xml


def test_kbk_roundtrip():
    kbk = ExpenseKBK.from_parts("020", "04", "11", "2010490019", "241")
    assert kbk.raw == "02004112010490019241"
    assert kbk.target_article == "2010490019"
    assert kbk.expense_type == "241"


def test_money_no_float():
    assert money_to_kopecks("1 234 567,89") == 123456789
    assert money_to_kopecks("-10,01") == -1001


def _xlsx_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "0503127"
    ws.append(["Отчет об исполнении бюджета"])
    ws.append(["Наименование показателя", "ГРБС", "Раздел", "Подраздел", "Целевая статья", "Вид расходов", "Бюджетные ассигнования", "Исполнено"])
    ws.append(["Связь", "020", "04", "11", "2010490019", "241", "1000,00", "900,25"])
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


def test_xlsx_inside_zip_to_records():
    outer = BytesIO()
    with ZipFile(outer, "w") as zf:
        zf.writestr("reports/report.xlsx", _xlsx_bytes())
    tables = list(iter_archive_tables(outer.getvalue(), "treasury.zip"))
    assert len(tables) == 1
    records = parse_table(tables[0], 2026, "roskazna")
    types = {r.record_type: r for r in records}
    assert types["FEDERAL_BUDGET_APPROPRIATION"].amount_kopecks == 100000
    assert types["FEDERAL_BUDGET_CASH_EXECUTION"].amount_kopecks == 90025
    assert types["FEDERAL_BUDGET_CASH_EXECUTION"].dimensions["kbk"] == "02004112010490019241"


def test_reconcile_and_graph():
    kbk = "02004112010490019241"
    base = {"budget_year": 2026, "currency": "RUB", "dimensions": {"kbk": kbk, "grbs": "020", "section": "04", "subsection": "11", "target_article": "2010490019", "expense_type": "241"}}
    records = [
        dict(base, record_type="FEDERAL_BUDGET_APPROPRIATION", amount_kopecks=100000),
        dict(base, record_type="FEDERAL_BUDGET_CASH_EXECUTION", amount_kopecks=90000),
    ]
    rows = reconcile(records)
    assert rows[0]["variance_to_control_plan_kopecks"] == 10000
    assert rows[0]["execution_basis_points"] == 9000
    graph = build_flow_graph(records)
    assert any(n["kind"] == "BUDGET_LINE" for n in graph["nodes"])
    assert any(e["kind"] == "CLASSIFIES" for e in graph["edges"])


def test_eis_contract_xml():
    xml = b'''<contract><regNum>012345</regNum><contractNumber>A-1</contractNumber><customer><inn>7700000000</inn></customer><suppliers><supplier><inn>7800000000</inn></supplier></suppliers><price>1234.56</price><kbk>02004112010490019241</kbk></contract>'''
    rows = parse_contract_xml(xml, "contract.xml", 2026)
    assert rows[0]["amount_kopecks"] == 123456
    assert rows[0]["dimensions"]["supplier_inn"] == "7800000000"
    assert rows[0]["dimensions"]["customer_inn"] == "7700000000"


def test_limit_is_control_plan_not_double_counted():
    kbk = "02004112010490019241"
    dims = {"kbk": kbk, "grbs": "020", "section": "04", "subsection": "11", "target_article": "2010490019", "expense_type": "241"}
    records = [
        {"budget_year": 2026, "record_type": "FEDERAL_BUDGET_APPROPRIATION", "amount_kopecks": 100000, "dimensions": dims},
        {"budget_year": 2026, "record_type": "FEDERAL_BUDGET_LIMIT", "amount_kopecks": 80000, "dimensions": dims},
        {"budget_year": 2026, "record_type": "FEDERAL_BUDGET_CASH_EXECUTION", "amount_kopecks": 70000, "dimensions": dims},
    ]
    row = reconcile(records)[0]
    assert row["control_plan_kopecks"] == 80000
    assert row["variance_to_control_plan_kopecks"] == 10000


def test_backfill_year_url():
    from synergy_budget.backfill import build_year_url
    url = build_year_url({"url": "https://example.test/report?filter_type=43", "archive_year_param": "filter_year"}, 2024)
    assert "filter_type=43" in url and "filter_year=2024" in url


def test_backfill_never_guesses_year_without_evidence():
    from synergy_budget.backfill import infer_report_year
    assert infer_report_year(2015, "https://example.test/report.zip") == (None, "unverified")
    assert infer_report_year(2015, "report_2015.zip") == (2015, "url_or_filename")
    assert infer_report_year(2015, "report_2026.zip") == (2026, "url_or_filename_override")
