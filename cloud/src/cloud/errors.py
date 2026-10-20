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
    "oauth_not_configured": {
        "en": "This sign-in method is not enabled on this MosaelCloud deployment yet. Contact the administrator.",
        "zh": "这个登录方式还没启用，请联系管理员。",
    },
    "oauth_state_invalid": {
        "en": "This sign-in attempt is invalid or has already been used. Start again from the sign-in page.",
        "zh": "这次登录的校验信息无效或已经用过，请回到登录页重新发起。",
    },
    "oauth_callback_invalid": {
        "en": "The provider sent us back without an authorization code. Start the sign-in again.",
        "zh": "第三方回调里没有授权码，请重新发起登录。",
    },
    "oauth_denied": {
        "en": "You cancelled the authorization at {provider}. Nothing on your MosaelCloud account changed.",
        "zh": "你在 {provider} 那边取消了授权，MosaelCloud 账号没有变化。",
    },
    "oauth_code_rejected": {
        "en": "The provider rejected the authorization code or the PKCE check. Start the sign-in again.",
        "zh": "第三方拒绝了这次授权码或 PKCE 校验，请重新发起登录。",
    },
    "oauth_email_unverified": {
        "en": "The provider did not return a verified email address, so it cannot sign you in to MosaelCloud. Verify the email with {provider} and try again.",
        "zh": "第三方没有返回已验证的邮箱，所以不能用来登录 MosaelCloud。请先在 {provider} 验证邮箱后再试。",
    },
    "oauth_identity_conflict": {
        "en": "This {provider} account is already bound to a different MosaelCloud account. Sign in to that account instead.",
        "zh": "这个 {provider} 账号已经绑到另一个 MosaelCloud 账号，请改为登录那个账号。",
    },
    "oauth_provider_error": {
        "en": "The provider did not answer correctly. Try again in a moment.",
        "zh": "第三方服务暂时没有正常响应，请稍后重试。",
    },
    "password_too_short": {
        "en": "The password must be at least {min} characters.",
        "zh": "密码至少要 {min} 个字符。",
    },
    "password_too_long": {
        "en": "The password must be at most {max} characters.",
        "zh": "密码最多 {max} 个字符。",
    },
    "identity_required": {
        "en": "Pick a display name first. It is the name other people will see next to your shares and comments.",
        "zh": "先起个名字再来发布或评论。这个名字会显示在别人看到的分享和评论旁边。",
    },
    "display_name_required": {
        "en": "The display name cannot be empty.",
        "zh": "昵称不能为空。",
    },
    "display_name_too_long": {
        "en": "The display name must be at most {max} characters.",
        "zh": "昵称最多 {max} 个字符。",
    },
    "handle_invalid": {
        "en": "Handles can only use lowercase letters, digits, hyphens and underscores, up to {max} characters.",
        "zh": "短名只能用英文小写字母、数字、连字符和下划线，最多 {max} 个字符。",
    },
    "handle_reserved": {
        "en": "That handle is reserved. Choose another one.",
        "zh": "这个短名是保留字，请换一个。",
    },
    "handle_taken": {
        "en": "That handle is already taken. Choose another one.",
        "zh": "这个短名已经有人用了，请换一个。",
    },
    "title_required": {
        "en": "A share needs a title.",
        "zh": "分享需要一个标题。",
    },
    "title_too_long": {
        "en": "The title must be at most {max} characters.",
        "zh": "标题最多 {max} 个字符。",
    },
    "summary_too_long": {
        "en": "The summary must be at most {max} characters.",
        "zh": "简介最多 {max} 个字符。",
    },
    "license_too_long": {
        "en": "The license name must be at most {max} characters.",
        "zh": "许可协议名称最多 {max} 个字符。",
    },
    "invalid_kind": {
        "en": "A share must be one of: {allowed}.",
        "zh": "分享类型只能是：{allowed}。",
    },
    "invalid_payload": {
        "en": "The share payload must be a JSON value.",
        "zh": "分享内容必须是一份 JSON。",
    },
    "payload_too_large": {
        "en": "This share is too large. The payload limit is {limit}.",
        "zh": "这份分享太大了，内容上限是 {limit}。",
    },
    "share_not_found": {
        "en": "That share does not exist, or it has been removed.",
        "zh": "这个分享不存在，或者已经被删除了。",
    },
    "comment_empty": {
        "en": "A comment cannot be empty.",
        "zh": "评论不能为空。",
    },
    "comment_too_long": {
        "en": "A comment must be at most {max} characters.",
        "zh": "评论最多 {max} 个字符。",
    },
    "comment_not_found": {
        "en": "That comment does not exist.",
        "zh": "这条评论不存在。",
    },
    "user_not_found": {
        "en": "No MosaelCloud account uses that handle.",
        "zh": "没有这个短名对应的账号。",
    },
    "invalid_cursor": {
        "en": "The page cursor is invalid. Start from the first page.",
        "zh": "翻页游标无效，请从第一页重新开始。",
    },
    "invalid_sort": {
        "en": "Sorting must be one of: {allowed}.",
        "zh": "排序只能是：{allowed}。",
    },
    "not_authenticated": {
        "en": "You are not signed in. Sign in and try again.",
        "zh": "你还没有登录，请登录后再试。",
    },
    "cross_site_request": {
        "en": "This request came from another site. Open Mosael and try again.",
        "zh": "这个请求来自别的网站，请在 Mosael 里重试。",
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
