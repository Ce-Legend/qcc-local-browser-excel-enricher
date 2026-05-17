from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha1
import json
from typing import Any


class Status(StrEnum):
    PENDING = "待采集"
    RUNNING = "采集中"
    SUCCESS = "成功"
    NO_MATCH = "未匹配"
    MULTIPLE_CANDIDATES = "多候选"
    NO_EMPLOYEE_COUNT = "无员工数"
    PERMISSION_DENIED = "权限不足"
    CAPTCHA = "验证码"
    ACCOUNT_ERROR = "账号异常"
    PAGE_ERROR = "页面异常"


@dataclass(slots=True)
class InputRecord:
    row_index: int
    company_name: str
    credit_code: str = ""
    region: str = ""
    original: dict[str, Any] = field(default_factory=dict)

    @property
    def row_key(self) -> str:
        payload = {
            "row_index": self.row_index,
            "company_name": self.company_name.strip(),
            "credit_code": self.credit_code.strip(),
            "region": self.region.strip(),
        }
        return sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(slots=True)
class ScrapeResult:
    row_key: str
    row_index: int
    original_name: str
    original_code: str = ""
    original_region: str = ""
    original_json: str = "{}"
    matched_name: str = ""
    matched_code: str = ""
    detail_url: str = ""
    year1: str = ""
    employee_count1: str = ""
    year2: str = ""
    employee_count2: str = ""
    year3: str = ""
    employee_count3: str = ""
    data_source: str = ""
    status: Status = Status.PENDING
    remark: str = ""
    attempts: int = 0
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @classmethod
    def from_record(cls, record: InputRecord, status: Status = Status.PENDING, remark: str = "") -> "ScrapeResult":
        return cls(
            row_key=record.row_key,
            row_index=record.row_index,
            original_name=record.company_name,
            original_code=record.credit_code,
            original_region=record.region,
            original_json=json.dumps(record.original, ensure_ascii=False),
            status=status,
            remark=remark,
        )

    def set_year_counts(self, values: list[tuple[str, str]]) -> None:
        slots = [
            ("year1", "employee_count1"),
            ("year2", "employee_count2"),
            ("year3", "employee_count3"),
        ]
        for (year_attr, count_attr), value in zip(slots, values[:3]):
            setattr(self, year_attr, value[0])
            setattr(self, count_attr, value[1])

    def to_export_row(self) -> dict[str, Any]:
        original = json.loads(self.original_json or "{}")
        row = dict(original)
        row.update(
            {
                "原始企业名称": self.original_name,
                "原始统一社会信用代码": self.original_code,
                "原始地区": self.original_region,
                "匹配企业名称": self.matched_name,
                "匹配统一社会信用代码": self.matched_code,
                "企查查详情页": self.detail_url,
                "年份1": self.year1,
                "员工数1": self.employee_count1,
                "年份2": self.year2,
                "员工数2": self.employee_count2,
                "年份3": self.year3,
                "员工数3": self.employee_count3,
                "数据来源": self.data_source,
                "采集状态": str(self.status),
                "备注": self.remark,
                "采集时间": self.updated_at,
            }
        )
        return row
