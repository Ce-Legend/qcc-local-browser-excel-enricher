from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import logging
from pathlib import Path
import sys

from dotenv import load_dotenv

from .delivery import (
    CDP_URL,
    build_customer_paths,
    ensure_customer_dirs,
    find_browser_executable,
    find_chrome_executable,
    find_single_input_excel,
    print_customer_paths,
    python_version_ok,
    write_customer_demo,
)
from .excel_io import load_input_excel, write_results_excel, write_sample_excel
from .models import ScrapeResult, Status
from .models import InputRecord
from .scraper import QccScraper
from .storage import ProgressStore


DEFAULT_PROFILE = "browser_profiles/qcc"
DEFAULT_DB = "data/progress.sqlite"
RETRIABLE_STATUSES = {Status.PAGE_ERROR}
SPEED_PRESETS = {
    "conservative": (60.0, 90.0),
    "aggressive": (30.0, 45.0),
}
FAILED_STATUSES = {
    Status.NO_MATCH,
    Status.MULTIPLE_CANDIDATES,
    Status.NO_EMPLOYEE_COUNT,
    Status.PERMISSION_DENIED,
    Status.CAPTCHA,
    Status.ACCOUNT_ERROR,
    Status.PAGE_ERROR,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qcc-employee-scraper", description="企查查员工数本地采集工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sample = subparsers.add_parser("init-sample", help="生成样例输入 Excel")
    sample.add_argument("--output", default="samples/input_sample.xlsx")

    customer_check = subparsers.add_parser("customer-check", help="客户交付版：检查目录、Python 和 Chrome/Edge")
    customer_check.add_argument("--root", default=".")

    customer_demo = subparsers.add_parser("customer-demo", help="客户交付版：在 input 文件夹生成 demo Excel")
    customer_demo.add_argument("--output", default="input/demo_companies.xlsx")
    customer_demo.add_argument("--overwrite", action="store_true")

    customer_paths = subparsers.add_parser("customer-paths", help="客户交付版：输出本次输入、进度库、结果文件路径")
    customer_paths.add_argument("--input-dir", default="input")

    login = subparsers.add_parser("login", help="打开独立浏览器并手动登录企查查")
    login.add_argument("--profile", default=DEFAULT_PROFILE)
    login.add_argument("--cdp-url", default="", help="连接已打开的浏览器调试端口，例如 http://127.0.0.1:3456")
    login.add_argument("--browser-channel", default="", help="使用本机浏览器通道，例如 chrome 或 msedge")
    login.add_argument("--executable-path", default="", help="使用指定浏览器可执行文件路径")
    login.add_argument("--headless", action="store_true")

    run = subparsers.add_parser("run", help="批量采集并导出结果")
    run.add_argument("--input", required=True)
    run.add_argument("--db", default=DEFAULT_DB)
    run.add_argument("--output", required=True)
    run.add_argument("--profile", default=DEFAULT_PROFILE)
    run.add_argument("--cdp-url", default="", help="连接已打开的浏览器调试端口，例如 http://127.0.0.1:3456")
    run.add_argument("--browser-channel", default="", help="使用本机浏览器通道，例如 chrome 或 msedge")
    run.add_argument("--executable-path", default="", help="使用指定浏览器可执行文件路径")
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--force", action="store_true", help="重新采集已成功记录")
    run.add_argument("--headless", action="store_true")
    run.add_argument(
        "--speed-mode",
        choices=["conservative", "aggressive", "custom"],
        default="conservative",
        help="速度模式：conservative=60-90秒/家，aggressive=30-45秒/家，custom=使用自定义间隔",
    )
    run.add_argument("--min-delay", type=float, default=None, help="自定义每家企业之间的最短间隔秒数")
    run.add_argument("--max-delay", type=float, default=None, help="自定义每家企业之间的最长间隔秒数")
    run.add_argument("--retries", type=int, default=1, help="页面异常时额外重试次数")
    run.add_argument("--log", default="logs/run.log")
    run.add_argument("--overwrite", action="store_true", help="允许覆盖已存在的导出文件")
    run.add_argument("--stop-on-block", action="store_true", help="遇到验证码、访问频繁或账号异常时立即停止")
    run.add_argument("--wait-on-block", action="store_true", help="遇到验证/账号拦截时等待人工处理，解除后继续当前企业")
    run.add_argument("--block-wait-timeout", type=float, default=1800.0, help="等待人工解除验证的最长秒数")
    run.add_argument("--block-poll-interval", type=float, default=5.0, help="检测验证是否解除的间隔秒数")
    run.add_argument("--stop-after-success", type=int, default=0, help="成功采集 N 条后停止，便于分批运行")
    run.add_argument("--max-records-before-pause", type=int, default=0, help="每处理 N 条后自动长暂停一次")
    run.add_argument("--pause-min", type=float, default=300.0, help="自动长暂停最短秒数")
    run.add_argument("--pause-max", type=float, default=600.0, help="自动长暂停最长秒数")

    export = subparsers.add_parser("export", help="从进度库导出 Excel")
    export.add_argument("--db", default=DEFAULT_DB)
    export.add_argument("--output", required=True)
    export.add_argument("--overwrite", action="store_true", help="允许覆盖已存在的导出文件")
    export.add_argument("--failed-only", action="store_true", help="只导出非成功状态记录，便于人工复核或补跑")
    return parser


def setup_logging(path: str) -> None:
    log_path = Path(path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )


def resolve_output_path(path: str, overwrite: bool) -> Path:
    output = Path(path)
    if overwrite or not output.exists():
        return output
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output.with_name(f"{output.stem}_{stamp}{output.suffix}")


def filter_results(results: list[ScrapeResult], *, failed_only: bool = False) -> list[ScrapeResult]:
    if not failed_only:
        return results
    return [result for result in results if result.status in FAILED_STATUSES]


def results_for_records(store: ProgressStore, records: list[InputRecord]) -> list[ScrapeResult]:
    results: list[ScrapeResult] = []
    for record in records:
        result = store.get(record.row_key)
        if result is not None:
            results.append(result)
    return results


def summarize_results(results: list[ScrapeResult]) -> dict[str, int]:
    return dict(Counter(str(result.status) for result in results))


def resolve_delay_range(args: argparse.Namespace) -> tuple[float, float]:
    min_delay, max_delay = SPEED_PRESETS.get(args.speed_mode, SPEED_PRESETS["conservative"])
    if args.min_delay is not None:
        min_delay = args.min_delay
    if args.max_delay is not None:
        max_delay = args.max_delay
    if min_delay < 0 or max_delay < 0 or min_delay > max_delay:
        raise ValueError("--min-delay / --max-delay 参数不合法：必须为非负数，且 min-delay <= max-delay")
    return min_delay, max_delay


def cmd_init_sample(args: argparse.Namespace) -> int:
    write_sample_excel(args.output)
    print(f"已生成样例输入：{args.output}")
    return 0


def cmd_customer_check(args: argparse.Namespace) -> int:
    ensure_customer_dirs(args.root)
    print("目录检查：OK")
    print(f"Python 版本：{sys.version.split()[0]} {'OK' if python_version_ok() else '不满足 3.11+'}")
    browser_path = find_browser_executable()
    chrome_path = find_chrome_executable()
    if browser_path:
        label = "Chrome" if chrome_path else "Edge"
        print(f"浏览器检查：OK ({label}: {browser_path})")
    else:
        print("浏览器检查：未找到 Chrome 或 Edge。请安装 Google Chrome：https://www.google.cn/chrome/")
    print("Python 依赖：如果本命令能正常显示，说明项目依赖已可用。")
    return 0 if python_version_ok() and browser_path else 1


def cmd_customer_demo(args: argparse.Namespace) -> int:
    ensure_customer_dirs()
    output = write_customer_demo(args.output, overwrite=args.overwrite)
    print(f"Demo Excel：{output}")
    return 0


def cmd_customer_paths(args: argparse.Namespace) -> int:
    ensure_customer_dirs()
    try:
        input_file = find_single_input_excel(args.input_dir)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR={exc}")
        return 1
    paths = build_customer_paths(input_file)
    print_customer_paths(paths)
    print(f"CDP_URL={CDP_URL}")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    with QccScraper(
        args.profile,
        cdp_url=args.cdp_url,
        browser_channel=args.browser_channel,
        executable_path=args.executable_path,
        headless=args.headless,
    ) as scraper:
        scraper.open_login_page()
        print("已打开企查查登录页。请在浏览器里完成会员登录，完成后回到终端按回车。")
        input()
    print(f"登录态已保存到：{args.profile}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    setup_logging(args.log)
    try:
        min_delay, max_delay = resolve_delay_range(args)
    except ValueError as exc:
        print(str(exc))
        return 1
    records = load_input_excel(args.input)
    if args.limit:
        records = records[: args.limit]
    if not records:
        print("输入文件没有可采集记录。")
        return 1

    output_path = resolve_output_path(args.output, args.overwrite)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logging.info(
        "run start input=%s db=%s output=%s records=%s speed_mode=%s delay=%s-%s retries=%s wait_on_block=%s stop_on_block=%s",
        args.input,
        args.db,
        output_path,
        len(records),
        args.speed_mode,
        min_delay,
        max_delay,
        args.retries,
        args.wait_on_block,
        args.stop_on_block,
    )
    with ProgressStore(args.db) as store:
        store.seed_pending(ScrapeResult.from_record(record, Status.PENDING) for record in records)
        with QccScraper(
            args.profile,
            cdp_url=args.cdp_url,
            browser_channel=args.browser_channel,
            executable_path=args.executable_path,
            headless=args.headless,
        ) as scraper:
            success_count = 0
            processed_since_pause = 0
            try:
                for index, record in enumerate(records, start=1):
                    if store.should_skip_success(record.row_key, force=args.force):
                        print(f"[{index}/{len(records)}] 跳过已成功：{record.company_name}")
                        continue
                    print(f"[{index}/{len(records)}] 采集：{record.company_name}")
                    logging.info("start row=%s company=%s", record.row_index, record.company_name)
                    result = ScrapeResult.from_record(record, Status.PAGE_ERROR, remark="尚未开始")
                    manual_unblock_count = 0
                    while True:
                        for attempt in range(args.retries + 1):
                            running = ScrapeResult.from_record(record, Status.RUNNING)
                            store.upsert(running)
                            result = scraper.scrape_record(record)
                            store.upsert(result)
                            logging.info(
                                "finish row=%s company=%s status=%s remark=%s attempt=%s",
                                record.row_index,
                                record.company_name,
                                result.status,
                                result.remark,
                                attempt + 1,
                            )
                            if result.status not in RETRIABLE_STATUSES:
                                break
                            if attempt < args.retries:
                                print(f"  -> {result.status}，准备重试 {attempt + 1}/{args.retries}")
                                scraper.random_sleep(min_delay, max_delay)
                        if not (args.wait_on_block and result.status in {Status.CAPTCHA, Status.ACCOUNT_ERROR}):
                            break
                        manual_unblock_count += 1
                        print("  -> 检测到验证/账号拦截，请在打开的浏览器窗口中手动完成扫码或验证。")
                        print(
                            "  -> 工具会低频检测是否解除，解除后自动继续；"
                            "如果页面没有自动恢复，可在浏览器里手动刷新一次。"
                        )
                        unblocked = scraper.wait_for_manual_unblock(
                            timeout_seconds=args.block_wait_timeout,
                            poll_seconds=args.block_poll_interval,
                        )
                        if not unblocked:
                            print("  -> 等待超时，已保留当前进度。")
                            break
                        print("  -> 验证已解除，重新采集当前企业。")
                        logging.info(
                            "manual unblock row=%s company=%s count=%s",
                            record.row_index,
                            record.company_name,
                            manual_unblock_count,
                        )
                    print(f"  -> {result.status} {result.remark}".rstrip())
                    processed_since_pause += 1
                    if result.status == Status.SUCCESS:
                        success_count += 1
                    if args.stop_on_block and result.status in {Status.CAPTCHA, Status.ACCOUNT_ERROR}:
                        print("检测到验证/账号拦截，已按 --stop-on-block 停止。")
                        break
                    if args.stop_after_success and success_count >= args.stop_after_success:
                        print(f"已成功采集 {success_count} 条，按 --stop-after-success 停止。")
                        break
                    if args.max_records_before_pause and processed_since_pause >= args.max_records_before_pause:
                        print(
                            f"已处理 {processed_since_pause} 条，自动暂停 "
                            f"{args.pause_min:g}-{args.pause_max:g} 秒。"
                        )
                        scraper.random_sleep(args.pause_min, args.pause_max)
                        processed_since_pause = 0
                    scraper.random_sleep(min_delay, max_delay)
            except KeyboardInterrupt:
                print("收到中断，已保留当前进度。")

        results = results_for_records(store, records)
        write_results_excel(results, output_path)
        print(f"已导出：{output_path}")
        summary = summarize_results(results)
        print("状态统计：", summary)
        logging.info("run exported output=%s result_count=%s summary=%s", output_path, len(results), summary)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    output_path = resolve_output_path(args.output, args.overwrite)
    with ProgressStore(args.db) as store:
        results = filter_results(store.all_results(), failed_only=args.failed_only)
        write_results_excel(results, output_path)
        print(f"已导出：{output_path}")
        print("状态统计：", summarize_results(results))
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init-sample":
        return cmd_init_sample(args)
    if args.command == "customer-check":
        return cmd_customer_check(args)
    if args.command == "customer-demo":
        return cmd_customer_demo(args)
    if args.command == "customer-paths":
        return cmd_customer_paths(args)
    if args.command == "login":
        return cmd_login(args)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "export":
        return cmd_export(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
