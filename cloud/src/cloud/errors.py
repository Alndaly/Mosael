"""给人看的失败说明:**中英两份一起回**。

官网按自己当前的语言挑一条;桌面端经本地后端转述时拿到的也是同一份。错误码是给程序看的,
文案是给人看的 —— 两者都不该只有一种。
"""

from __future__ import annotations

#: code → {语言: 模板}。模板里的 `{name}` 由抛错处填。
MESSAGES: dict[str, dict[str, str]] = {
    "invalid_request": {
        "en": "The request is missing something or has the wrong shape. Check the email and password.",
        "zh": "请求格式不对或缺少内容，请检查邮箱和密码。",
    },
    "email_taken": {
        "en": "That email is already registered. Try signing in instead.",
        "zh": "这个邮箱已经注册过了，请直接登录。",
    },
    "invalid_credentials": {
        "en": "Email or password is incorrect.",
        "zh": "邮箱或密码不正确。",
    },
    "email_code_required": {
        "en": "Enter the 6-digit code we emailed you.",
        "zh": "请输入邮箱收到的 6 位验证码。",
    },
    "email_code_invalid": {
        "en": "That code is not correct. Check the email and try again.",
        "zh": "验证码不正确，请核对邮件后重试。",
    },
    "email_code_expired": {
        "en": "That code has expired. Request a new one.",
        "zh": "验证码已过期，请重新获取。",
    },
    "email_code_used": {
        "en": "That code has already been used. Request a new one.",
        "zh": "验证码已经用过了，请重新获取。",
    },
    "email_code_attempts_exhausted": {
        "en": "Too many wrong codes. Request a new one.",
        "zh": "验证码错误次数过多，请重新获取。",
    },
    "email_code_cooldown": {
        "en": "Wait {seconds} seconds before requesting another code.",
        "zh": "请等 {seconds} 秒后再重新发送验证码。",
    },
    "too_many_requests": {
        "en": "Too many requests from here. Try again later.",
        "zh": "操作太频繁，请稍后再试。",
    },
    "mail_not_configured": {
        "en": "Email delivery is not configured on this service yet. Contact the administrator.",
        "zh": "这台服务还没配置发信，请联系管理员。",
    },
    "email_send_failed": {
        "en": "The code could not be emailed. Try again in a moment.",
        "zh": "验证码邮件没有发出去，请稍后重试。",
    },
    "password_too_short": {
        "en": "The password must be at least {min} characters.",
        "zh": "密码至少要 {min} 个字符。",
    },
    "password_too_long": {
        "en": "The password must be at most {max} characters.",
        "zh": "密码最多 {max} 个字符。",
    },
    "not_authenticated": {
        "en": "You are not signed in. Sign in and try again.",
        "zh": "你还没有登录，请登录后再试。",
    },
    "invalid_device_token": {
        "en": "This device credential is invalid or has been revoked.",
        "zh": "这台设备的凭据无效，或者已经被撤销。",
    },
    "cross_site_request": {
        "en": "This request came from another site. Open Mosael and try again.",
        "zh": "这个请求来自别的网站，请在 Mosael 里重试。",
    },
    "device_code_invalid": {
        "en": "This device code is unknown. Start the binding again from Mosael.",
        "zh": "设备码不存在，请在 Mosael 里重新发起绑定。",
    },
    "device_code_expired": {
        "en": "This device code has expired. Start the binding again from Mosael.",
        "zh": "设备码已过期，请在 Mosael 里重新发起绑定。",
    },
    "device_code_used": {
        "en": "This device code has already been used. Start the binding again.",
        "zh": "设备码已经用过了，请重新发起绑定。",
    },
    "authorization_pending": {
        "en": "Waiting for you to approve this device on the Mosael website.",
        "zh": "等待你在 Mosael 官网上确认这台设备。",
    },
    "user_code_invalid": {
        "en": "That confirmation code does not exist. Check the code shown in Mosael.",
        "zh": "确认码不存在，请核对 Mosael 里显示的那一串。",
    },
    "user_code_used": {
        "en": "This confirmation code has already been claimed.",
        "zh": "这个确认码已经被别的账号用掉了。",
    },
    "device_not_found": {
        "en": "That device is not bound to your account.",
        "zh": "这台设备不在你的账号下。",
    },
    "access_denied": {
        "en": "This account can no longer authorize the device.",
        "zh": "这个账号已经不能授权这台设备了。",
    },
    "not_found": {
        "en": "No such endpoint.",
        "zh": "没有这个接口。",
    },
    "method_not_allowed": {
        "en": "That method is not allowed here.",
        "zh": "这个接口不接受这种请求方法。",
    },
    "internal_error": {
        "en": "MosaelCloud hit an internal error. Try again in a moment.",
        "zh": "MosaelCloud 出了点内部错误，请稍后重试。",
    },
}


def message(code: str, **params: object) -> dict[str, str]:
    entries = MESSAGES.get(code) or MESSAGES["internal_error"]
    return {language: template.format(**params) for language, template in entries.items()}


class CloudError(Exception):
    """一次可以照着说的失败:HTTP 状态 + 机器码 + 中英文各一句。"""

    def __init__(self, status_code: int, code: str, **params: object) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message(code, **params)
        super().__init__(f"{code}: {self.message['en']}")

    def body(self) -> dict[str, object]:
        return {"error": self.code, "message": self.message}
