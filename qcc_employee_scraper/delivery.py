from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from pathlib import Path
import os
import re
import shutil
import sys

from .excel_io import write_sample_excel


CUSTOMER_DIRS = ("input", "outputs", "data", "logs", "browser_profiles")
PROFILE_DIR = Path("browser_profiles") / "qcc_windows"
CDP_URL = "http://127.0.0.1:3456"


@dataclass(frozen=True, slots=True)
class CustomerPaths:
    input_file: Path
    db: Path
    output: Path
    failed_output: Path
    log: Path


def ensure_customer_dirs(root: str | Path = ".") -> None:
    root_path = Path(root)
    for dirname in CUSTOMER_DIRS:
        (root_path / dirname).mkdir(parents=True, exist_ok=True)
    (root_path / PROFILE_DIR).mkdir(parents=True, exist_ok=True)


def find_single_input_excel(input_dir: str | Path = "input") -> Path:
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"没有找到 input 文件夹：{input_path}")
    files = sorted(
        path
        for path in input_path.glob("*.xlsx")
        if path.is_file() and not path.name.startswith("~$")
    )
    if not files:
        raise FileNotFoundError("input 文件夹里没有 .xlsx 文件，请先放入一个待处理 Excel。")
    if len(files) > 1:
        names = "、".join(path.name for path in files)
        raise ValueError(f"input 文件夹里有多个 .xlsx 文件，请只保留一个后重试：{names}")
    return files[0]


def safe_task_name(path: str | Path) -> str:
    stem = Path(path).stem.strip()
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", stem)
    stem = stem.strip("_")
    return stem[:60] or "customer_input"


def input_file_fingerprint(path: str | Path) -> str:
    input_path = Path(path)
    try:
        payload = input_path.read_bytes()
    except FileNotFoundError:
        payload = str(input_path).encode("utf-8")
    return sha1(payload).hexdigest()[:10]


def build_customer_paths(input_file: str | Path, now: datetime | None = None) -> CustomerPaths:
    input_path = Path(input_file)
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    task_name = safe_task_name(input_path)
    fingerprint = input_file_fingerprint(input_path)
    return CustomerPaths(
        input_file=input_path,
        db=Path("data") / f"{task_name}_{fingerprint}_progress.sqlite",
        output=Path("outputs") / f"result_{stamp}.xlsx",
        failed_output=Path("outputs") / f"failed_only_{stamp}.xlsx",
        log=Path("logs") / f"run_{stamp}.log",
    )


def find_chrome_executable() -> str:
    command_path = shutil.which("chrome")
    if command_path:
        return command_path
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def find_edge_executable() -> str:
    command_path = shutil.which("msedge")
    if command_path:
        return command_path
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def find_browser_executable() -> str:
    return find_chrome_executable() or find_edge_executable()


def write_customer_demo(output_path: str | Path = "input/demo_companies.xlsx", *, overwrite: bool = False) -> Path:
    output = Path(output_path)
    if output.exists() and not overwrite:
        return output
    output.parent.mkdir(parents=True, exist_ok=True)
    write_sample_excel(output)
    return output


def print_customer_paths(paths: CustomerPaths) -> None:
    print(f"INPUT={paths.input_file}")
    print(f"DB={paths.db}")
    print(f"OUTPUT={paths.output}")
    print(f"FAILED_OUTPUT={paths.failed_output}")
    print(f"LOG={paths.log}")


def python_version_ok() -> bool:
    return sys.version_info >= (3, 11)
