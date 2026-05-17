from qcc_employee_scraper.captcha import CaptchaDetector


def test_detect_slider_captcha():
    event = CaptchaDetector.detect("请完成安全验证 拖动滑块到指定位置")
    assert event
    assert event.kind == "滑块验证"
    assert not event.can_auto_solve


def test_detect_sms_verification():
    event = CaptchaDetector.detect("请输入手机验证码完成短信验证")
    assert event
    assert event.kind == "短信验证"
    assert not event.can_auto_solve


def test_robot_business_word_is_not_captcha():
    assert CaptchaDetector.detect("深圳众擎机器人科技股份有限公司") is None


def test_detect_qcc_user_verification_page():
    event = CaptchaDetector.detect("用户验证 - 企查查 您的操作过于频繁，验证后再操作 验证一下")
    assert event
    assert event.kind == "访问频繁"
    assert not event.can_auto_solve


def test_detect_qcc_account_qr_verification_page():
    event = CaptchaDetector.detect("账号使用异常，已限制继续访问 可使用企查查APP 扫码解除限制")
    assert event
    assert event.kind == "设备验证"
    assert not event.can_auto_solve
