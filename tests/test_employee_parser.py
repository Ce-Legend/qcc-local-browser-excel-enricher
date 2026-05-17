from qcc_employee_scraper.models import InputRecord
from qcc_employee_scraper.scraper import QccScraper, SearchCandidate, normalize_export_counts, parse_employee_counts


def test_parse_tooltip_table_text():
    text = "员工人数 数据来源 2024年 2023年 2022年 工商年报 参保 5066 5410 6605"
    values, source = parse_employee_counts(text)
    assert values == [("2024", "5066"), ("2023", "5410"), ("2022", "6605")]
    assert source == "工商年报"


def test_parse_tooltip_table_text_with_arrow_marks_from_qcc():
    text = "员工人数 数据来源 2024年 2023年 2022年 工商年报 参保 17> 18> 12>"
    values, source = parse_employee_counts(text)

    assert values == [("2024", "17"), ("2023", "18"), ("2022", "12")]
    assert source == "工商年报"


def test_parse_tooltip_table_text_with_zero_as_unpublished_source_value():
    text = "员工人数 数据来源 2024年 2023年 2022年 工商年报 参保 20> 17> 0>"
    values, source = parse_employee_counts(text)

    assert values == [("2024", "20"), ("2023", "17"), ("2022", "0")]
    assert source == "工商年报"


def test_parse_direct_employee_text():
    text = "企业规模 大型 员工人数：5066（2024年）"
    values, source = parse_employee_counts(text)
    assert values == [("2024", "5066")]
    assert source == ""


def test_parse_merged_report_row_with_wan_unit():
    text = "员工人数 数据来源 2025年 2024年 2023年 合并报表 7.2万 70200 71090 工商年报 - 参保 5340 参保 5627"
    values, source = parse_employee_counts(text)
    assert values == [("2025", "72000"), ("2024", "70200"), ("2023", "71090")]
    assert source == "合并报表"


def test_parse_merged_report_row_before_other_rows():
    text = "员工人数 数据来源 2025年 2024年 2023年 合并报表 19952 19186 20223 公司报表 - 1 - 工商年报 - 参保 5119 参保 5394"
    values, source = parse_employee_counts(text)
    assert values == [("2025", "19952"), ("2024", "19186"), ("2023", "20223")]
    assert source == "合并报表"


def test_parse_annual_report_row_when_no_merged_report():
    text = "员工人数 数据来源 2025年 2024年 2023年 工商年报 0 3477 3521"
    values, source = parse_employee_counts(text)
    assert values == [("2025", "0"), ("2024", "3477"), ("2023", "3521")]
    assert source == "工商年报"


def test_does_not_mix_sources_when_merged_report_has_blank_year():
    text = "员工人数 数据来源 2025年 2024年 2023年 合并报表 124320 204891 - 工商年报 - 参保 1106 参保 884"
    values, source = parse_employee_counts(text)
    assert values == [("2025", "124320"), ("2024", "204891")]
    assert source == "合并报表"


def test_normalize_export_counts():
    assert normalize_export_counts([("2025", "0"), ("2024", "12")]) == [
        ("2025", "未公布"),
        ("2024", "12"),
        ("缺", "缺"),
    ]


def test_choose_candidate_by_credit_code():
    scraper = QccScraper("browser_profiles/test")
    record = InputRecord(row_index=2, company_name="理想汽车有限公司", credit_code="91110108MA01L4CP6C")
    candidates = [
        SearchCandidate("理想汽车有限公司", "https://example.com/a", "统一社会信用代码 91110108MA01L4CP6C"),
        SearchCandidate("理想汽车销售有限公司", "https://example.com/b", "统一社会信用代码 91110105MA00XXXXXX"),
    ]
    assert scraper._choose_candidate(candidates, record) == candidates[0]
