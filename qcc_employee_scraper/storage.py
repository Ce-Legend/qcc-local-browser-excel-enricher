from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Iterable

from .models import ScrapeResult, Status


SCHEMA = """
CREATE TABLE IF NOT EXISTS scrape_results (
    row_key TEXT PRIMARY KEY,
    row_index INTEGER NOT NULL,
    original_name TEXT NOT NULL,
    original_code TEXT DEFAULT '',
    original_region TEXT DEFAULT '',
    original_json TEXT DEFAULT '{}',
    matched_name TEXT DEFAULT '',
    matched_code TEXT DEFAULT '',
    detail_url TEXT DEFAULT '',
    year1 TEXT DEFAULT '',
    employee_count1 TEXT DEFAULT '',
    year2 TEXT DEFAULT '',
    employee_count2 TEXT DEFAULT '',
    year3 TEXT DEFAULT '',
    employee_count3 TEXT DEFAULT '',
    data_source TEXT DEFAULT '',
    status TEXT NOT NULL,
    remark TEXT DEFAULT '',
    attempts INTEGER DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


class ProgressStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ProgressStore":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def get(self, row_key: str) -> ScrapeResult | None:
        row = self.conn.execute("SELECT * FROM scrape_results WHERE row_key = ?", (row_key,)).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def should_skip_success(self, row_key: str, force: bool = False) -> bool:
        if force:
            return False
        row = self.conn.execute("SELECT status FROM scrape_results WHERE row_key = ?", (row_key,)).fetchone()
        return bool(row and row["status"] == Status.SUCCESS)

    def upsert(self, result: ScrapeResult) -> None:
        existing = self.get(result.row_key)
        attempts = result.attempts
        if existing:
            should_count_attempt = existing.status == Status.RUNNING and result.status not in {Status.PENDING, Status.RUNNING}
            attempts = max(result.attempts, existing.attempts + (1 if should_count_attempt else 0))
        self.conn.execute(
            """
            INSERT INTO scrape_results (
                row_key, row_index, original_name, original_code, original_region, original_json,
                matched_name, matched_code, detail_url,
                year1, employee_count1, year2, employee_count2, year3, employee_count3,
                data_source, status, remark, attempts, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(row_key) DO UPDATE SET
                row_index = excluded.row_index,
                original_name = excluded.original_name,
                original_code = excluded.original_code,
                original_region = excluded.original_region,
                original_json = excluded.original_json,
                matched_name = excluded.matched_name,
                matched_code = excluded.matched_code,
                detail_url = excluded.detail_url,
                year1 = excluded.year1,
                employee_count1 = excluded.employee_count1,
                year2 = excluded.year2,
                employee_count2 = excluded.employee_count2,
                year3 = excluded.year3,
                employee_count3 = excluded.employee_count3,
                data_source = excluded.data_source,
                status = excluded.status,
                remark = excluded.remark,
                attempts = excluded.attempts,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                result.row_key,
                result.row_index,
                result.original_name,
                result.original_code,
                result.original_region,
                result.original_json,
                result.matched_name,
                result.matched_code,
                result.detail_url,
                result.year1,
                result.employee_count1,
                result.year2,
                result.employee_count2,
                result.year3,
                result.employee_count3,
                result.data_source,
                str(result.status),
                result.remark,
                attempts,
            ),
        )
        self.conn.commit()

    def all_results(self) -> list[ScrapeResult]:
        rows = self.conn.execute("SELECT * FROM scrape_results ORDER BY row_index").fetchall()
        return [self._from_row(row) for row in rows]

    def summary(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT status, COUNT(*) AS count FROM scrape_results GROUP BY status").fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def seed_pending(self, results: Iterable[ScrapeResult]) -> None:
        for result in results:
            if self.get(result.row_key) is None:
                self.upsert(result)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ScrapeResult:
        return ScrapeResult(
            row_key=row["row_key"],
            row_index=row["row_index"],
            original_name=row["original_name"],
            original_code=row["original_code"] or "",
            original_region=row["original_region"] or "",
            original_json=row["original_json"] or "{}",
            matched_name=row["matched_name"] or "",
            matched_code=row["matched_code"] or "",
            detail_url=row["detail_url"] or "",
            year1=row["year1"] or "",
            employee_count1=row["employee_count1"] or "",
            year2=row["year2"] or "",
            employee_count2=row["employee_count2"] or "",
            year3=row["year3"] or "",
            employee_count3=row["employee_count3"] or "",
            data_source=row["data_source"] or "",
            status=Status(row["status"]),
            remark=row["remark"] or "",
            attempts=row["attempts"] or 0,
            updated_at=row["updated_at"] or "",
        )
