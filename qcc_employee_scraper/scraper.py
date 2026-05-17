from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
from random import uniform
import re
import time
from urllib.parse import quote

from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from .captcha import CaptchaDetector
from .captcha import CaptchaEvent
from .models import InputRecord, ScrapeResult, Status


QCC_HOME = "https://www.qcc.com/"
QCC_SEARCH = "https://www.qcc.com/web/search?key={keyword}"
LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SearchCandidate:
    name: str
    url: str
    snippet: str = ""


def parse_employee_counts(text: str) -> tuple[list[tuple[str, str]], str]:
    direct = _parse_direct_employee_count(text)
    normalized = re.sub(r"\s+", " ", text)
    years = []
    for year in re.findall(r"(20\d{2})年", normalized):
        if year not in years:
            years.append(year)
    if not years:
        return [], ""

    source = ""
    if "工商年报" in normalized and "参保" in normalized:
        source = "工商年报/参保"
    elif "工商年报" in normalized:
        source = "工商年报"
    elif "参保" in normalized:
        source = "参保"

    if "数据来源" in normalized or "合并报表" in normalized or "工商年报" in normalized:
        structured, structured_source = _parse_structured_employee_table(normalized, years)
        if structured:
            return structured, structured_source or source

    if direct:
        return direct, source
    return [], source


def _parse_direct_employee_count(text: str) -> list[tuple[str, str]]:
    match = re.search(r"员工人数[:：]\s*([0-9,.]+)\s*万?\s*[（(](20\d{2})年[）)]", text)
    if not match:
        return []
    value = _normalize_count_token(match.group(1))
    if not value:
        return []
    return [(match.group(2), value)]


def _parse_structured_employee_table(text: str, years: list[str]) -> tuple[list[tuple[str, str]], str]:
    target_years = years[:3]
    rows = {
        label: _row_values_after_label(text, label, len(target_years))
        for label in ("合并报表", "公司报表", "工商年报")
    }
    for label, values in rows.items():
        if len(values) == len(target_years) and all(value is not None for value in values):
            return list(zip(target_years, values)), label

    best_label = ""
    best_pairs: list[tuple[str, str]] = []
    for label, values in rows.items():
        pairs = [
            (year, value)
            for year, value in zip(target_years, values)
            if value is not None
        ]
        if len(pairs) > len(best_pairs):
            best_label = label
            best_pairs = pairs
    return best_pairs, best_label


def _row_values_after_label(text: str, label: str, count: int) -> list[str | None]:
    start = text.find(label)
    if start == -1:
        return []
    stop = len(text)
    for next_label in ("合并报表", "公司报表", "工商年报", "营业收入", "简介", "所属集团"):
        next_start = text.find(next_label, start + len(label))
        if next_start != -1:
            stop = min(stop, next_start)
    segment = text[start + len(label) : stop]
    values: list[str | None] = []
    for token in re.findall(r"-|[0-9][0-9,.]*\s*万?", segment):
        value = _normalize_count_token(token)
        values.append(value)
        if len(values) == count:
            return values
    return []


def _normalize_count_token(token: str) -> str | None:
    token = token.strip().replace(",", "")
    if not token or token == "-":
        return None
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(万?)", token)
    if not match:
        return None
    number = float(match.group(1))
    if match.group(2) == "万":
        number *= 10000
    if not number.is_integer():
        return str(round(number, 2)).rstrip("0").rstrip(".")
    return str(int(number))


def normalize_export_counts(values: list[tuple[str, str]], total_slots: int = 3) -> list[tuple[str, str]]:
    normalized: list[tuple[str, str]] = []
    for year, count in values[:total_slots]:
        normalized.append((year, "未公布" if count == "0" else count))
    while len(normalized) < total_slots:
        normalized.append(("缺", "缺"))
    return normalized


def _compact_log_text(text: str, limit: int = 500) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


class QccScraper:
    def __init__(
        self,
        profile_dir: str | Path,
        *,
        cdp_url: str = "",
        browser_channel: str = "",
        executable_path: str = "",
        captcha_log_dir: str | Path = "logs/captcha",
        evidence_log_dir: str | Path = "logs/evidence",
        headless: bool = False,
        timeout_ms: int = 30000,
        slow_mo_ms: int = 80,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.cdp_url = cdp_url
        self.browser_channel = browser_channel
        self.executable_path = executable_path
        self.captcha_log_dir = Path(captcha_log_dir)
        self.evidence_log_dir = Path(evidence_log_dir)
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.slow_mo_ms = slow_mo_ms
        self._playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self._created_page: Page | None = None
        self._owns_context = True
        self._last_employee_debug: dict[str, object] = {}

    def __enter__(self) -> "QccScraper":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        if self.cdp_url:
            self.browser = self._playwright.chromium.connect_over_cdp(self.cdp_url)
            self.context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
            self._owns_context = False
            self.page = self.context.new_page()
            self._created_page = self.page
        else:
            launch_options = {
                "user_data_dir": str(self.profile_dir),
                "headless": self.headless,
                "slow_mo": self.slow_mo_ms,
                "viewport": {"width": 1440, "height": 950},
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if self.browser_channel:
                launch_options["channel"] = self.browser_channel
            if self.executable_path:
                launch_options["executable_path"] = self.executable_path
            self.context = self._playwright.chromium.launch_persistent_context(
                **launch_options,
            )
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.context.set_default_timeout(self.timeout_ms)
        return self

    def __exit__(self, *_args: object) -> None:
        if self._created_page and self._owns_context:
            self._created_page.close()
        if self.context and self._owns_context:
            self.context.close()
        if self._playwright:
            self._playwright.stop()

    def open_login_page(self) -> None:
        page = self._require_page()
        page.goto(QCC_HOME, wait_until="domcontentloaded")

    def scrape_record(self, record: InputRecord) -> ScrapeResult:
        result = ScrapeResult.from_record(record, status=Status.RUNNING)
        try:
            keyword = record.credit_code or record.company_name
            LOGGER.info(
                "scrape start row=%s company=%s credit_code=%s region=%s keyword=%s",
                record.row_index,
                record.company_name,
                record.credit_code,
                record.region,
                keyword,
            )
            self._goto_search(keyword)
            account_error = self._detect_account_error()
            if account_error:
                result.status = Status.ACCOUNT_ERROR
                result.remark = account_error
                return result
            event = self._detect_blocking_event()
            if event:
                artifact = self._save_captcha_artifact(record, "search", event.kind)
                result.status = self._status_for_blocking_event(event)
                result.remark = f"{event.message}；记录：{artifact}"
                return result

            candidates = self._collect_candidates()
            LOGGER.info(
                "search candidates row=%s company=%s count=%s top=%s",
                record.row_index,
                record.company_name,
                len(candidates),
                [f"{item.name}|{item.url}" for item in candidates[:5]],
            )
            if not candidates:
                artifact = self._save_evidence_artifact(record, "未匹配", "搜索结果中未找到企业详情页")
                result.status = Status.NO_MATCH
                result.remark = f"搜索结果中未找到企业详情页；证据：{artifact}"
                return result

            candidate = self._choose_candidate(candidates, record)
            if candidate is None:
                candidate_text = "\n".join(f"- {item.name} {item.url}" for item in candidates[:10])
                artifact = self._save_evidence_artifact(record, "多候选", candidate_text)
                result.status = Status.MULTIPLE_CANDIDATES
                result.remark = f"存在多个候选，无法自动确认；证据：{artifact}"
                return result

            result.matched_name = candidate.name
            result.detail_url = candidate.url
            LOGGER.info(
                "candidate chosen row=%s company=%s matched=%s url=%s",
                record.row_index,
                record.company_name,
                candidate.name,
                candidate.url,
            )
            self._goto_detail(candidate.url)
            account_error = self._detect_account_error()
            if account_error:
                result.status = Status.ACCOUNT_ERROR
                result.remark = account_error
                return result
            event = self._detect_blocking_event()
            if event:
                artifact = self._save_captcha_artifact(record, "detail", event.kind)
                result.status = self._status_for_blocking_event(event)
                result.remark = f"{event.message}；记录：{artifact}"
                return result

            detail_text = self._body_text()
            matched_code = self._extract_credit_code(detail_text)
            if matched_code:
                result.matched_code = matched_code
            LOGGER.info(
                "detail loaded row=%s company=%s matched_code=%s detail_url=%s",
                record.row_index,
                record.company_name,
                matched_code,
                self._require_page().url,
            )
            if record.credit_code and matched_code and record.credit_code != matched_code:
                artifact = self._save_evidence_artifact(
                    record,
                    "信用代码不一致",
                    f"输入信用代码：{record.credit_code}\n页面信用代码：{matched_code}",
                )
                result.status = Status.MULTIPLE_CANDIDATES
                result.remark = f"匹配企业信用代码与输入不一致，需人工确认；证据：{artifact}"
                return result
            values, data_source = self._extract_employee_counts()
            if len(values) < 3:
                debug_text = self._format_employee_debug(values, data_source)
                artifact = self._save_evidence_artifact(record, "员工数不完整", debug_text)
                if values:
                    result.set_year_counts(normalize_export_counts(values))
                    result.data_source = data_source
                    if data_source:
                        result.status = Status.SUCCESS
                        result.remark = f"同一数据来源仅公开 {len(values)} 年，缺失年份已填“缺”；证据：{artifact}"
                    else:
                        result.status = Status.NO_EMPLOYEE_COUNT
                        result.remark = f"仅提取到页面直接显示的单年员工数，未捕获三年浮层，需复核；证据：{artifact}"
                else:
                    result.set_year_counts(normalize_export_counts([]))
                    result.status = Status.NO_EMPLOYEE_COUNT
                    result.remark = f"详情页未提取到最近三年员工人数；证据：{artifact}"
                return result

            result.set_year_counts(normalize_export_counts(values))
            result.data_source = data_source
            result.status = Status.SUCCESS
            result.remark = "页面显示 0，已按未公布导出" if any(count == "0" for _year, count in values) else ""
            return result
        except PlaywrightTimeoutError as exc:
            result.status = Status.PAGE_ERROR
            result.remark = f"页面超时：{exc}"
            return result
        except Exception as exc:  # noqa: BLE001
            result.status = Status.PAGE_ERROR
            result.remark = f"{type(exc).__name__}: {exc}"
            return result

    def random_sleep(self, min_seconds: float, max_seconds: float) -> None:
        time.sleep(uniform(min_seconds, max_seconds))

    def current_block_reason(self) -> str:
        account_error = self._detect_account_error()
        if account_error:
            return account_error
        event = self._detect_blocking_event()
        if event:
            return event.message
        return ""

    def wait_for_manual_unblock(self, *, timeout_seconds: float, poll_seconds: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not self.current_block_reason():
                return True
            time.sleep(poll_seconds)
        return False

    def _require_page(self) -> Page:
        if self.page is None:
            raise RuntimeError("浏览器尚未启动")
        return self.page

    def _goto_search(self, keyword: str) -> None:
        page = self._require_page()
        url = QCC_SEARCH.format(keyword=quote(keyword.strip()))
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=15000)

    def _goto_detail(self, url: str) -> None:
        page = self._require_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle", timeout=15000)

    def _body_text(self) -> str:
        page = self._require_page()
        try:
            return page.locator("body").inner_text(timeout=5000)
        except PlaywrightTimeoutError:
            return ""

    def _detect_blocking_event(self):
        page = self._require_page()
        title = page.title()
        has_captcha_widget = page.locator(
            ".geetest_panel, .geetest_window, .geetest_box, .nc-container, "
            "[class*='captcha'], [id*='captcha'], iframe[src*='captcha'], iframe[src*='geetest']"
        ).count()
        text = self._body_text()
        event = CaptchaDetector.detect(f"{title}\n{text}")
        if event and (has_captcha_widget or event.kind in {"短信验证", "设备验证", "滑块验证", "图片验证码", "访问频繁"}):
            return event
        if has_captcha_widget and event:
            return event
        return None

    def _status_for_blocking_event(self, event: CaptchaEvent) -> Status:
        if event.kind in {"短信验证", "设备验证"}:
            return Status.ACCOUNT_ERROR
        return Status.CAPTCHA

    def _detect_account_error(self) -> str:
        page = self._require_page()
        url = page.url
        text = self._body_text()
        compact = text.replace(" ", "").replace("\n", "")
        if "/weblogin" in url or ("会员登录" in text and "短信/密码登录" in text):
            return "未登录或登录态失效：当前页面为企查查登录页"
        if "登录后查看更多" in compact or "登录/注册" in compact:
            return "未登录或权限不足：页面要求登录后查看"
        return ""

    def _save_captcha_artifact(self, record: InputRecord, stage: str, kind: str) -> str:
        page = self._require_page()
        self.captcha_log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", record.company_name)[:40]
        stem = f"{stamp}_{record.row_index}_{stage}_{kind}_{name}"
        screenshot_path = self.captcha_log_dir / f"{stem}.png"
        text_path = self.captcha_log_dir / f"{stem}.txt"
        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            screenshot_path = self.captcha_log_dir / f"{stem}_screenshot_failed.png"
        qr_crop_path = self._save_qr_crop_artifact(stem)
        text = f"URL: {page.url}\nTITLE: {page.title()}\nSTAGE: {stage}\nKIND: {kind}\nCOMPANY: {record.company_name}\n\n{self._body_text()[:8000]}"
        if qr_crop_path:
            text = text.replace("\n\n", f"\nQR_CROP: {qr_crop_path}\n\n", 1)
        text_path.write_text(text, encoding="utf-8")
        return str(screenshot_path)

    def _save_qr_crop_artifact(self, stem: str) -> str:
        page = self._require_page()
        text = self._body_text()
        if not any(keyword in text for keyword in ("扫码", "二维码", "企查查APP", "企查查 APP")):
            return ""
        try:
            clips = page.evaluate(
                """
                () => {
                  const selectors = [
                    'img',
                    'canvas',
                    'svg',
                    '[class*="qr" i]',
                    '[id*="qr" i]',
                    '[class*="qrcode" i]',
                    '[id*="qrcode" i]',
                    '[class*="code" i]',
                    '[id*="code" i]'
                  ];
                  const seen = new Set();
                  const candidates = [];
                  for (const node of document.querySelectorAll(selectors.join(','))) {
                    if (seen.has(node)) continue;
                    seen.add(node);
                    const style = window.getComputedStyle(node);
                    const rect = node.getBoundingClientRect();
                    if (style.visibility === 'hidden' || style.display === 'none') continue;
                    if (rect.width < 80 || rect.height < 80 || rect.width > 520 || rect.height > 520) continue;
                    const ratio = rect.width / rect.height;
                    if (ratio < 0.7 || ratio > 1.35) continue;
                    const text = (node.innerText || node.alt || node.title || node.className || node.id || '').toString();
                    const sourceScore = ['IMG', 'CANVAS', 'SVG'].includes(node.tagName) ? 3 : 0;
                    const qrScore = /qr|qrcode|二维码|扫码|code/i.test(text) ? 2 : 0;
                    candidates.push({
                      x: Math.max(0, rect.left + window.scrollX - 12),
                      y: Math.max(0, rect.top + window.scrollY - 12),
                      width: rect.width + 24,
                      height: rect.height + 24,
                      score: sourceScore + qrScore + Math.min(rect.width, rect.height) / 1000
                    });
                  }
                  return candidates.sort((a, b) => b.score - a.score).slice(0, 3);
                }
                """
            )
            if not clips:
                return ""
            crop_path = self.captcha_log_dir / f"{stem}_二维码裁剪.png"
            page.screenshot(path=str(crop_path), clip=clips[0])
            return str(crop_path)
        except Exception:
            return ""

    def _save_evidence_artifact(self, record: InputRecord, reason: str, extra_text: str = "") -> str:
        page = self._require_page()
        self.evidence_log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", record.company_name)[:40]
        reason_slug = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", reason)[:20]
        stem = f"{stamp}_{record.row_index}_{reason_slug}_{name}"
        screenshot_path = self.evidence_log_dir / f"{stem}.png"
        text_path = self.evidence_log_dir / f"{stem}.txt"
        try:
            page.screenshot(path=str(screenshot_path), full_page=True)
        except Exception:
            screenshot_path = self.evidence_log_dir / f"{stem}_screenshot_failed.png"
        text = (
            f"URL: {page.url}\n"
            f"TITLE: {page.title()}\n"
            f"REASON: {reason}\n"
            f"COMPANY: {record.company_name}\n"
            f"CREDIT_CODE: {record.credit_code}\n"
            f"REGION: {record.region}\n\n"
            f"{extra_text}\n\n"
            f"{self._body_text()[:8000]}"
        )
        text_path.write_text(text, encoding="utf-8")
        return str(screenshot_path)

    def _collect_candidates(self) -> list[SearchCandidate]:
        page = self._require_page()
        links = page.locator('a[href*="/firm/"]')
        count = min(links.count(), 20)
        candidates: list[SearchCandidate] = []
        seen: set[str] = set()
        for index in range(count):
            link = links.nth(index)
            href = link.get_attribute("href") or ""
            if not href:
                continue
            if href.startswith("/"):
                href = f"https://www.qcc.com{href}"
            if href in seen:
                continue
            text = re.sub(r"\s+", " ", link.inner_text(timeout=3000)).strip()
            if not text:
                text = link.get_attribute("title") or ""
            if not text:
                continue
            snippet = self._candidate_snippet(link, text)
            seen.add(href)
            candidates.append(SearchCandidate(name=text, url=href, snippet=snippet))
        return candidates

    def _choose_candidate(self, candidates: list[SearchCandidate], record: InputRecord) -> SearchCandidate | None:
        if record.credit_code:
            by_code = [item for item in candidates if record.credit_code in item.snippet]
            if len(by_code) == 1:
                return by_code[0]
        if len(candidates) == 1:
            return candidates[0]
        exact = [item for item in candidates if item.name == record.company_name]
        if len(exact) == 1:
            return exact[0]
        contains = [item for item in candidates if record.company_name in item.name or item.name in record.company_name]
        if len(contains) == 1:
            return contains[0]
        return None

    def _candidate_snippet(self, link, fallback: str) -> str:
        try:
            return link.evaluate(
                """
                (node) => {
                  let current = node;
                  for (let i = 0; i < 6 && current; i += 1) {
                    const text = (current.innerText || '').replace(/\\s+/g, ' ').trim();
                    if (text.length >= 20 && text.length <= 1200) return text;
                    current = current.parentElement;
                  }
                  return (node.innerText || '').replace(/\\s+/g, ' ').trim();
                }
                """
            )
        except Exception:
            return fallback

    def _extract_credit_code(self, text: str) -> str:
        patterns = [
            r"统一社会信用代码[:：\s]*([0-9A-Z]{18})",
            r"信用代码[:：\s]*([0-9A-Z]{18})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return ""

    def _extract_employee_counts(self) -> tuple[list[tuple[str, str]], str]:
        tooltip_texts = self._collect_employee_texts_with_hover()
        best_values: list[tuple[str, str]] = []
        best_source = ""
        self._last_employee_debug = {
            "tooltip_texts": tooltip_texts,
            "parsed": [],
            "direct_texts": [],
            "direct_values": [],
        }
        LOGGER.info("employee tooltip candidates count=%s", len(tooltip_texts))
        for index, text in enumerate(tooltip_texts, start=1):
            values, source = parse_employee_counts(text)
            self._last_employee_debug["parsed"].append({"index": index, "values": values, "source": source})
            LOGGER.info(
                "employee tooltip candidate index=%s values=%s source=%s text=%s",
                index,
                values,
                source,
                _compact_log_text(text, 700),
            )
            if len(values) >= 3:
                return values, source
            if len(values) > len(best_values):
                best_values = values
                best_source = source
        if best_values:
            return best_values, best_source
        direct, direct_texts = self._extract_direct_employee_count()
        self._last_employee_debug["direct_texts"] = direct_texts
        self._last_employee_debug["direct_values"] = direct
        LOGGER.info("employee direct fallback values=%s texts=%s", direct, direct_texts)
        if direct:
            return direct, ""
        return [], ""

    def _collect_employee_texts_with_hover(self) -> list[str]:
        collected: list[str] = []

        def remember(stage: str) -> None:
            texts = self._candidate_employee_texts()
            added = 0
            for text in texts:
                if text not in collected:
                    collected.append(text)
                    added += 1
            LOGGER.info("employee hover stage=%s candidate_count=%s added=%s", stage, len(texts), added)

        remember("before-hover")
        self._hover_employee_area(remember)
        return collected

    def _hover_employee_area(self, remember=None) -> None:
        page = self._require_page()
        locators = [
            page.locator(".staff.app-business-pop .ui-dropdown-pop"),
            page.locator(".staff.app-business-pop"),
            page.locator(".app-business-pop").filter(has_text="员工人数"),
            page.get_by_text("员工人数", exact=False),
            page.locator("text=员工人数"),
        ]
        for locator_index, locator in enumerate(locators, start=1):
            try:
                count = min(locator.count(), 3)
                for index in range(count):
                    target = locator.nth(index)
                    target.scroll_into_view_if_needed(timeout=5000)
                    target.hover(timeout=5000)
                    page.wait_for_timeout(1500)
                    if remember:
                        remember(f"locator-{locator_index}-{index + 1}")
            except Exception as exc:
                LOGGER.info("employee locator hover failed locator=%s error=%s", locator_index, exc)
                continue
        for index, point in enumerate(self._employee_hover_points(), start=1):
            try:
                page.mouse.move(float(point["x"]), float(point["y"]))
                page.wait_for_timeout(1500)
                if remember:
                    remember(f"point-{index}-{point.get('label', '')}")
            except Exception as exc:
                LOGGER.info("employee point hover failed point=%s error=%s", point, exc)

    def _candidate_employee_texts(self) -> list[str]:
        page = self._require_page()
        script = """
        () => {
          const out = [];
          const pushSnippet = (text, reason) => {
            if (!text) return;
            const clean = text.replace(/\\s+/g, ' ').trim();
            if (!clean) return;
            const yearCount = (clean.match(/20\\d{2}年/g) || []).length;
            const hasEmployeeKeyword =
              clean.includes('员工人数') ||
              clean.includes('数据来源') ||
              clean.includes('工商年报') ||
              clean.includes('参保') ||
              clean.includes('合并报表') ||
              clean.includes('公司报表');
            if (yearCount < 2 || !hasEmployeeKeyword) return;
            if (clean.length <= 1800) {
              out.push(clean);
              return;
            }
            for (const keyword of ['员工人数', '数据来源', '工商年报', '参保']) {
              const pos = clean.indexOf(keyword);
              if (pos === -1) continue;
              const start = Math.max(0, pos - 120);
              out.push(clean.slice(start, pos + 1200));
            }
          };
          const nodes = Array.from(document.querySelectorAll('body *'));
          for (const node of nodes) {
            const style = window.getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            if (style.visibility === 'hidden' || style.display === 'none' || rect.width === 0 || rect.height === 0) continue;
            const text = (node.innerText || '').trim();
            pushSnippet(text, 'node');
          }
          pushSnippet(document.body ? document.body.innerText || '' : '', 'body');
          return Array.from(new Set(out)).sort((a, b) => a.length - b.length).slice(0, 20);
        }
        """
        try:
            return page.evaluate(script)
        except Exception:
            return []

    def _employee_hover_points(self) -> list[dict[str, object]]:
        page = self._require_page()
        script = """
        () => {
          const points = [];
          const seen = new Set();
          const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
          const visible = (node) => {
            if (!node || !(node instanceof Element)) return false;
            const style = window.getComputedStyle(node);
            const rect = node.getBoundingClientRect();
            return (
              style.visibility !== 'hidden' &&
              style.display !== 'none' &&
              rect.width > 0 &&
              rect.height > 0 &&
              rect.bottom >= 0 &&
              rect.right >= 0 &&
              rect.top <= window.innerHeight &&
              rect.left <= window.innerWidth
            );
          };
          const add = (node, label) => {
            if (!visible(node)) return;
            const rect = node.getBoundingClientRect();
            const key = `${Math.round(rect.left)}:${Math.round(rect.top)}:${Math.round(rect.width)}:${Math.round(rect.height)}:${label}`;
            if (seen.has(key)) return;
            seen.add(key);
            const y = clamp(rect.top + rect.height / 2, 1, window.innerHeight - 1);
            points.push({
              x: clamp(rect.right - 6, 1, window.innerWidth - 1),
              y,
              label: `${label}-right`
            });
            points.push({
              x: clamp(rect.left + Math.min(rect.width / 2, 42), 1, window.innerWidth - 1),
              y,
              label: `${label}-center`
            });
          };
          for (const node of Array.from(document.querySelectorAll('.staff.app-business-pop, .app-business-pop, .ui-dropdown-pop'))) {
            const text = (node.innerText || '').replace(/\\s+/g, ' ').trim();
            if (text.includes('员工人数')) add(node, 'class');
          }
          for (const node of Array.from(document.querySelectorAll('body *'))) {
            const text = (node.innerText || '').replace(/\\s+/g, ' ').trim();
            if (!text.includes('员工人数') || text.length > 260) continue;
            add(node, 'text');
            add(node.parentElement, 'parent');
            for (const child of Array.from(node.querySelectorAll('i, svg, span, em, [class*="icon"], [class*="question"], [class*="tip"], [class*="pop"]'))) {
              add(child, 'icon');
            }
          }
          return points.slice(0, 30);
        }
        """
        try:
            return page.evaluate(script)
        except Exception as exc:
            LOGGER.info("employee hover point discovery failed error=%s", exc)
            return []

    def _extract_direct_employee_count(self) -> tuple[list[tuple[str, str]], list[str]]:
        page = self._require_page()
        try:
            texts = page.evaluate(
                """
                () => Array.from(document.querySelectorAll('body *'))
                  .map(node => (node.innerText || '').trim())
                  .filter(text => /^员工人数[:：]\\s*[0-9,.]+\\s*万?\\s*[（(]20\\d{2}年[）)]$/.test(text))
                  .slice(0, 3)
                """
            )
        except Exception:
            return [], []
        for text in texts:
            match = re.search(r"员工人数[:：]\s*([0-9,.]+)\s*万?\s*[（(](20\d{2})年[）)]", text)
            if match:
                value = _normalize_count_token(match.group(1))
                if value:
                    return [(match.group(2), value)], texts
        return [], texts

    def _format_employee_debug(self, values: list[tuple[str, str]], data_source: str) -> str:
        tooltip_texts = self._last_employee_debug.get("tooltip_texts", [])
        parsed = self._last_employee_debug.get("parsed", [])
        direct_texts = self._last_employee_debug.get("direct_texts", [])
        direct_values = self._last_employee_debug.get("direct_values", [])
        lines = [
            f"已提取：{values}",
            f"数据来源：{data_source}",
            f"直接显示单年候选：{direct_values}",
            f"直接显示文本：{direct_texts}",
            f"浮层候选数量：{len(tooltip_texts) if isinstance(tooltip_texts, list) else 0}",
            f"浮层解析结果：{parsed}",
        ]
        if isinstance(tooltip_texts, list):
            for index, text in enumerate(tooltip_texts[:8], start=1):
                lines.append(f"\n--- 浮层候选 {index} ---\n{_compact_log_text(str(text), 1500)}")
        return "\n".join(lines)
