from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .models import InputRecord, ScrapeResult


HEADER_ALIASES = {
    "company_name": ["company_name", "company", "name", "企业名称", "公司名称", "公司名", "企业名", "名称"],
    "credit_code": [
        "credit_code",
        "unified_social_credit_code",
        "统一社会信用代码",
        "社会信用代码",
        "信用代码",
        "统一信用代码",
    ],
    "region": ["region", "area", "province", "city", "地区", "省市", "省份", "省份地区", "城市", "所在地"],
}

OUTPUT_COLUMNS = [
    "原始企业名称",
    "原始统一社会信用代码",
    "原始地区",
    "匹配企业名称",
    "匹配统一社会信用代码",
    "企查查详情页",
    "年份1",
    "员工数1",
    "年份2",
    "员工数2",
    "年份3",
    "员工数3",
    "数据来源",
    "采集状态",
    "备注",
    "采集时间",
]


def _clean(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _find_column(columns: list[str], aliases: list[str]) -> str | None:
    normalized = {column.strip(): column for column in columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return None


def load_input_excel(path: str | Path) -> list[InputRecord]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"输入文件不存在：{path}")

    df = pd.read_excel(path, dtype=str).fillna("")
    columns = [str(column).strip() for column in df.columns]
    df.columns = columns

    company_col = _find_column(columns, HEADER_ALIASES["company_name"])
    code_col = _find_column(columns, HEADER_ALIASES["credit_code"])
    region_col = _find_column(columns, HEADER_ALIASES["region"])
    if not company_col:
        raise ValueError(
            "输入 Excel 必须至少包含公司名称列，可用表头：company_name、企业名称、公司名称、公司名、企业名、名称"
        )

    records: list[InputRecord] = []
    for idx, row in df.iterrows():
        original = {column: _clean(row[column]) for column in columns}
        company_name = _clean(row[company_col])
        if not company_name:
            continue
        records.append(
            InputRecord(
                row_index=int(idx) + 2,
                company_name=company_name,
                credit_code=_clean(row[code_col]) if code_col else "",
                region=_clean(row[region_col]) if region_col else "",
                original=original,
            )
        )
    return records


def write_results_excel(results: list[ScrapeResult], output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [result.to_export_row() for result in sorted(results, key=lambda item: item.row_index)]
    df = pd.DataFrame(rows)
    for column in OUTPUT_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    front = [column for column in OUTPUT_COLUMNS if column in df.columns]
    rest = [column for column in df.columns if column not in front]
    df = df[front + rest]
    df.to_excel(output_path, index=False)


def write_sample_excel(output_path: str | Path) -> None:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"企业名称": "星河样例科技有限公司", "统一社会信用代码": "", "地区": "北京"},
        {"企业名称": "青舟样例信息技术有限公司", "统一社会信用代码": "", "地区": "深圳"},
        {"企业名称": "北辰样例智能装备有限公司", "统一社会信用代码": "", "地区": "上海"},
        {"企业名称": "云岚样例数据服务有限公司", "统一社会信用代码": "", "地区": "杭州"},
        {"企业名称": "澄川样例供应链有限公司", "统一社会信用代码": "", "地区": "广州"},
        {"企业名称": "南序样例软件有限公司", "统一社会信用代码": "", "地区": "成都"},
    ]
    pd.DataFrame(rows).to_excel(output_path, index=False)
