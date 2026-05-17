from datetime import datetime
from hashlib import sha1
from pathlib import Path

import pytest

from qcc_employee_scraper.delivery import build_customer_paths, find_single_input_excel, input_file_fingerprint, safe_task_name


def test_find_single_input_excel_requires_file(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="没有 .xlsx 文件"):
        find_single_input_excel(input_dir)


def test_find_single_input_excel_rejects_multiple_files(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.xlsx").write_bytes(b"")
    (input_dir / "b.xlsx").write_bytes(b"")

    with pytest.raises(ValueError, match="多个 .xlsx 文件"):
        find_single_input_excel(input_dir)


def test_find_single_input_excel_ignores_excel_temp_files(tmp_path: Path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "~$demo.xlsx").write_bytes(b"")
    expected = input_dir / "demo.xlsx"
    expected.write_bytes(b"")

    assert find_single_input_excel(input_dir) == expected


def test_build_customer_paths_uses_input_stem_and_content_hash_for_progress_db(tmp_path: Path):
    input_file = tmp_path / "input" / "sample company list.xlsx"
    input_file.parent.mkdir()
    input_file.write_bytes(b"demo-content")
    fingerprint = sha1(b"demo-content").hexdigest()[:10]

    paths = build_customer_paths(input_file, now=datetime(2026, 5, 14, 12, 30, 0))

    assert paths.db == Path(f"data/sample_company_list_{fingerprint}_progress.sqlite")
    assert paths.output == Path("outputs/result_20260514_123000.xlsx")
    assert paths.failed_output == Path("outputs/failed_only_20260514_123000.xlsx")
    assert paths.log == Path("logs/run_20260514_123000.log")


def test_input_file_fingerprint_changes_when_content_changes(tmp_path: Path):
    input_file = tmp_path / "same_name.xlsx"
    input_file.write_bytes(b"first")
    first = input_file_fingerprint(input_file)
    input_file.write_bytes(b"second")
    second = input_file_fingerprint(input_file)

    assert first != second


def test_safe_task_name_falls_back_for_blank_names():
    assert safe_task_name("input/!!!.xlsx") == "customer_input"
