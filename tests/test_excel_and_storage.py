from pathlib import Path

import pandas as pd

from qcc_employee_scraper.cli import build_parser, filter_results, resolve_delay_range, results_for_records, summarize_results
from qcc_employee_scraper.excel_io import load_input_excel, write_results_excel
from qcc_employee_scraper.models import InputRecord, ScrapeResult, Status
from qcc_employee_scraper.storage import ProgressStore


def test_load_input_excel_with_aliases(tmp_path: Path):
    input_path = tmp_path / "input.xlsx"
    pd.DataFrame(
        [
            {"公司名称": "星河样例科技有限公司", "社会信用代码": "CODE1", "省市": "北京"},
            {"公司名称": "", "社会信用代码": "CODE2", "省市": "深圳"},
        ]
    ).to_excel(input_path, index=False)

    records = load_input_excel(input_path)

    assert len(records) == 1
    assert records[0].company_name == "星河样例科技有限公司"
    assert records[0].credit_code == "CODE1"
    assert records[0].region == "北京"


def test_load_input_excel_with_minimum_company_name_column(tmp_path: Path):
    input_path = tmp_path / "input_minimum.xlsx"
    pd.DataFrame([{"company_name": "青舟样例信息技术有限公司"}]).to_excel(input_path, index=False)

    records = load_input_excel(input_path)

    assert len(records) == 1
    assert records[0].company_name == "青舟样例信息技术有限公司"
    assert records[0].credit_code == ""
    assert records[0].region == ""


def test_storage_resume_and_export(tmp_path: Path):
    db_path = tmp_path / "progress.sqlite"
    output_path = tmp_path / "result.xlsx"
    with ProgressStore(db_path) as store:
        result = ScrapeResult(
            row_key="key1",
            row_index=2,
            original_name="星河样例科技有限公司",
            status=Status.SUCCESS,
        )
        result.set_year_counts([("2024", "5066"), ("2023", "5410"), ("2022", "6605")])
        store.upsert(result)
        assert store.should_skip_success("key1")
        write_results_excel(store.all_results(), output_path)

    df = pd.read_excel(output_path, dtype=str).fillna("")
    assert df.loc[0, "采集状态"] == "成功"
    assert df.loc[0, "年份1"] == "2024"
    assert df.loc[0, "员工数1"] == "5066"


def test_filter_failed_only_excludes_success_and_pending():
    results = [
        ScrapeResult(row_key="success", row_index=2, original_name="A", status=Status.SUCCESS),
        ScrapeResult(row_key="pending", row_index=3, original_name="B", status=Status.PENDING),
        ScrapeResult(row_key="no_match", row_index=4, original_name="C", status=Status.NO_MATCH),
        ScrapeResult(row_key="captcha", row_index=5, original_name="D", status=Status.CAPTCHA),
    ]

    failed = filter_results(results, failed_only=True)

    assert [item.row_key for item in failed] == ["no_match", "captcha"]


def test_results_for_records_ignores_old_rows_in_progress_db(tmp_path: Path):
    db_path = tmp_path / "progress.sqlite"
    current = InputRecord(row_index=2, company_name="当前公司")
    old = InputRecord(row_index=3, company_name="旧公司")
    with ProgressStore(db_path) as store:
        store.upsert(ScrapeResult.from_record(current, Status.SUCCESS))
        store.upsert(ScrapeResult.from_record(old, Status.NO_MATCH))

        results = results_for_records(store, [current])

    assert [result.original_name for result in results] == ["当前公司"]
    assert summarize_results(results) == {"成功": 1}


def test_speed_mode_defaults_to_conservative():
    parser = build_parser()
    args = parser.parse_args(["run", "--input", "in.xlsx", "--output", "out.xlsx"])

    assert resolve_delay_range(args) == (60.0, 90.0)


def test_speed_mode_aggressive_is_half_conservative_interval():
    parser = build_parser()
    args = parser.parse_args(["run", "--input", "in.xlsx", "--output", "out.xlsx", "--speed-mode", "aggressive"])

    assert resolve_delay_range(args) == (30.0, 45.0)


def test_custom_delay_overrides_speed_mode():
    parser = build_parser()
    args = parser.parse_args(
        [
            "run",
            "--input",
            "in.xlsx",
            "--output",
            "out.xlsx",
            "--speed-mode",
            "conservative",
            "--min-delay",
            "10",
            "--max-delay",
            "12",
        ]
    )

    assert resolve_delay_range(args) == (10.0, 12.0)
