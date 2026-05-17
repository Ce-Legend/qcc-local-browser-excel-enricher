from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CaptchaEvent:
    kind: str
    message: str
    can_auto_solve: bool = False


class CaptchaDetector:
    KEYWORDS = {
        "短信验证": ["短信验证码", "手机验证码", "短信验证"],
        "设备验证": ["设备验证", "验证设备", "登录保护", "账号使用异常", "已限制继续访问", "扫码解除限制"],
        "滑块验证": ["滑块", "拖动滑块", "安全验证"],
        "图片验证码": ["图片验证码", "请输入验证码", "图形验证码"],
        "访问频繁": ["访问过于频繁", "操作频繁", "操作过于频繁", "请求过于频繁", "用户验证", "验证一下", "稍后再试"],
        "人机验证": ["人机验证", "请完成验证", "请完成安全验证", "行为验证", "智能验证"],
    }

    @classmethod
    def detect(cls, text: str) -> CaptchaEvent | None:
        compact = text.replace(" ", "").replace("\n", "")
        for kind, keywords in cls.KEYWORDS.items():
            if any(keyword in compact for keyword in keywords):
                return CaptchaEvent(kind=kind, message=f"检测到{kind}", can_auto_solve=False)
        return None
