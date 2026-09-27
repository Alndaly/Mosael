"""错误:统一 `{"error": {"code": "…", "message": "…"}}`,`message` 按 Accept-Language 给中文或英文。

`code` 是给程序读的稳定标识,`message` 是给人读的一句话。领域代码只抛 `ApiError(status, code, **params)`,
句子在这里的表里 —— 和桌面后端「领域里存 key,出口才翻」同一个做法。格式校验的错误(插件包、工作流文件、
画板快照)来自 mosael_formats,它们的句子在那边,按同一个语言说。
"""

from __future__ import annotations

from string import Formatter

from mosael_formats.i18n import DEFAULT_LOCALE, LOCALES, FormatError, current_locale

MESSAGES: dict[str, dict[str, str]] = {
    # ---- 通用 ----
    "invalid_request": {"zh": "请求参数不对:{fields}", "en": "Invalid request: {fields}"},
    "not_found": {"zh": "找不到这个地址", "en": "Not found."},
    "method_not_allowed": {"zh": "这个地址不支持这种请求方法", "en": "Method not allowed."},
    "unauthorized": {"zh": "请先登录", "en": "Please sign in first."},
    "token_expired": {"zh": "登录已过期,请刷新", "en": "Your session token has expired; refresh it."},
    "forbidden": {"zh": "没有权限做这件事", "en": "You don't have permission to do that."},
    "banned": {"zh": "这个账号已被停用", "en": "This account has been suspended."},
    "rate_limited": {"zh": "操作太频繁,请稍后再试", "en": "Too many requests. Please try again later."},
    "body_too_large": {"zh": "上传的内容超过大小上限({limit})", "en": "The request is larger than allowed ({limit})."},
    "internal_error": {"zh": "服务出了点问题,请稍后再试", "en": "Something went wrong on our side. Please try again later."},
    # ---- 短信与验证码 ----
    "invalid_phone": {"zh": "手机号格式不对", "en": "That phone number doesn't look right."},
    "invalid_purpose": {"zh": "验证码用途只能是 login、bind 或 reset", "en": "The purpose must be login, bind or reset."},
    "captcha_required": {"zh": "请先完成人机验证", "en": "Please complete the captcha first."},
    "captcha_failed": {"zh": "人机验证没有通过,请重试", "en": "The captcha check failed. Please try again."},
    "sms_too_frequent": {
        "zh": "验证码发送太频繁,请 {seconds} 秒后再试",
        "en": "Codes are being sent too often. Try again in {seconds} seconds.",
    },
    "sms_daily_limit": {
        "zh": "这个号码今天收到的验证码已达上限,请明天再试",
        "en": "This number has received the maximum number of codes for today. Try again tomorrow.",
    },
    "sms_ip_limit": {
        "zh": "当前网络发送验证码太多,请稍后再试",
        "en": "Too many codes have been requested from this network. Try again later.",
    },
    "sms_send_failed": {"zh": "短信发送失败,请稍后再试", "en": "Couldn't send the text message. Please try again later."},
    "code_invalid": {"zh": "验证码不对", "en": "That code is incorrect."},
    "code_expired": {"zh": "验证码已失效,请重新获取", "en": "That code has expired. Request a new one."},
    "code_attempts_exceeded": {
        "zh": "验证码输错次数太多,请重新获取",
        "en": "Too many wrong attempts. Request a new code.",
    },
    "phone_taken": {"zh": "这个手机号已经注册过了,请直接登录", "en": "This phone number is already registered. Sign in instead."},
    # ---- 协议 ----
    "terms_required": {
        "zh": "请先阅读并同意《用户协议》和《隐私政策》",
        "en": "Please read and accept the Terms of Service and Privacy Policy.",
    },
    "terms_outdated": {
        "zh": "《用户协议》《隐私政策》已更新,请重新阅读并同意",
        "en": "The Terms of Service and Privacy Policy have been updated. Please review and accept them again.",
    },
    # ---- 账号 ----
    "handle_invalid": {
        "zh": "用户名只能用 3 到 24 个小写字母、数字或下划线",
        "en": "Usernames are 3–24 lowercase letters, digits or underscores.",
    },
    "handle_taken": {"zh": "这个用户名已经被用了", "en": "That username is taken."},
    "handle_reserved": {"zh": "这个用户名是保留的,换一个吧", "en": "That username is reserved. Please pick another."},
    "handle_change_used": {"zh": "用户名只能改一次,已经改过了", "en": "You can change your username only once, and you already have."},
    "display_name_invalid": {"zh": "昵称长度要在 1 到 64 个字之间", "en": "Display names must be 1–64 characters."},
    "avatar_invalid": {"zh": "头像必须是一张已经上传的图片", "en": "The avatar must be an uploaded image."},
    "password_too_weak": {
        "zh": "密码至少 8 位,且不能超过 128 位",
        "en": "Passwords must be 8–128 characters long.",
    },
    "password_required": {"zh": "请输入当前密码", "en": "Enter your current password."},
    "invalid_credentials": {"zh": "用户名或密码不对", "en": "Incorrect username or password."},
    "login_locked": {
        "zh": "密码错误次数太多,请 {minutes} 分钟后再试,或用短信验证码登录",
        "en": "Too many failed attempts. Try again in {minutes} minutes, or sign in with a text code.",
    },
    # ---- 令牌与会话 ----
    "refresh_missing": {"zh": "缺少刷新令牌,请重新登录", "en": "No refresh token. Please sign in again."},
    "refresh_invalid": {"zh": "登录状态已失效,请重新登录", "en": "Your sign-in is no longer valid. Please sign in again."},
    "refresh_reused": {
        "zh": "检测到登录凭据被重复使用,为安全起见这台设备已下线,请重新登录",
        "en": "A sign-in credential was reused, so this device was signed out for safety. Please sign in again.",
    },
    "session_expired": {"zh": "登录已过期,请重新登录", "en": "Your session has expired. Please sign in again."},
    "csrf_header_missing": {
        "zh": "请求缺少 X-Requested-With 头",
        "en": "The request is missing the X-Requested-With header.",
    },
    "session_not_found": {"zh": "没有这个登录会话", "en": "No such session."},
    # ---- 设备授权 ----
    "device_code_invalid": {"zh": "设备码无效", "en": "Invalid device code."},
    "authorization_pending": {"zh": "等待在网页上确认", "en": "Waiting for approval in the browser."},
    "slow_down": {"zh": "轮询太快了,请放慢", "en": "Polling too fast; slow down."},
    "expired_token": {"zh": "这次授权已过期,请在应用里重新发起", "en": "This authorization has expired. Start again from the app."},
    "access_denied": {"zh": "授权被拒绝", "en": "Authorization was denied."},
    "user_code_invalid": {"zh": "没有找到这个授权码,请核对应用里显示的那串字", "en": "No such code. Check the code shown in the app."},
    "user_code_used": {"zh": "这个授权码已经被使用", "en": "This code has already been used."},
    # ---- 提交 ----
    "file_required": {"zh": "请选择要上传的文件", "en": "Choose a file to upload."},
    "file_too_large": {"zh": "文件超过大小上限({limit})", "en": "The file is larger than allowed ({limit})."},
    "invalid_file": {"zh": "{detail}", "en": "{detail}"},
    "title_required": {"zh": "请填写标题", "en": "Please enter a title."},
    "title_too_long": {"zh": "标题太长了", "en": "The title is too long."},
    "tags_invalid": {"zh": "标签最多 8 个,每个不超过 32 个字", "en": "Up to 8 tags, each at most 32 characters."},
    "cover_invalid": {"zh": "封面必须是 PNG、JPEG 或 WebP 图片", "en": "The cover must be a PNG, JPEG or WebP image."},
    "plugin_id_taken": {
        "zh": "插件 id「{plugin_id}」已经被别人占用了,请在清单里换一个 id",
        "en": "The plugin id “{plugin_id}” belongs to someone else. Use a different id in the manifest.",
    },
    "plugin_id_mismatch": {
        "zh": "包里的插件 id 是「{plugin_id}」,不是这一项",
        "en": "The package's plugin id is “{plugin_id}”, which doesn't match this item.",
    },
    "plugin_version_invalid": {
        "zh": "插件版本号「{version}」不是语义化版本(如 1.2.3)",
        "en": "The plugin version “{version}” is not a semantic version (like 1.2.3).",
    },
    "version_exists": {"zh": "版本 {version} 已经提交过了", "en": "Version {version} has already been submitted."},
    "version_not_newer": {
        "zh": "新版本 {version} 必须比已有的 {latest} 新",
        "en": "The new version {version} must be newer than {latest}.",
    },
    "not_owner": {"zh": "只有作者本人可以这样做", "en": "Only the author can do that."},
    "item_not_found": {"zh": "没有找到这一项", "en": "Not found."},
    "item_hidden": {"zh": "这一项已被下架", "en": "This item has been taken down."},
    "report_duplicate": {"zh": "你已经举报过它了,我们会尽快处理", "en": "You've already reported this. We'll look into it."},
    "report_reason_invalid": {"zh": "请选择举报原因", "en": "Please choose a reason."},
    "submission_not_pending": {"zh": "这次提交已经审核过了", "en": "This submission has already been reviewed."},
    "kind_invalid": {"zh": "类型只能是 workflows、plugins 或 shares", "en": "The kind must be workflows, plugins or shares."},
    # ---- 文件与分享 ----
    "blob_hash_invalid": {"zh": "文件哈希必须是 64 位小写十六进制", "en": "The file hash must be 64 lowercase hex characters."},
    "content_type_not_allowed": {
        "zh": "不支持这种文件类型:{content_type}。支持的类型:{allowed}",
        "en": "This file type isn't supported: {content_type}. Supported types: {allowed}",
    },
    "quota_exceeded": {"zh": "存储空间不够了(上限 {limit})", "en": "You've run out of storage (limit {limit})."},
    "upload_token_invalid": {"zh": "上传地址无效或已过期,请重新获取", "en": "The upload URL is invalid or has expired. Request a new one."},
    "hash_mismatch": {
        "zh": "上传的内容和声明的哈希对不上",
        "en": "The uploaded content doesn't match the declared hash.",
    },
    "size_mismatch": {"zh": "上传的大小和声明的不一致", "en": "The uploaded size doesn't match the declared size."},
    "unknown_blob": {
        "zh": "快照引用了没有上传过的文件:{sha256}",
        "en": "The snapshot references a file that hasn't been uploaded: {sha256}",
    },
    "invalid_snapshot": {"zh": "{detail}", "en": "{detail}"},
    "share_too_large": {"zh": "这张画板的文件总量超过上限({limit})", "en": "This board's files exceed the limit ({limit})."},
    "board_key_invalid": {"zh": "board_key 不合法", "en": "Invalid board_key."},
    "visibility_invalid": {"zh": "可见性只能是 unlisted 或 public", "en": "Visibility must be unlisted or public."},
    "share_not_found": {"zh": "没有找到这个分享", "en": "No such shared board."},
    "share_revoked": {"zh": "这个分享已被作者撤回", "en": "The author has withdrawn this shared board."},
    "share_removed": {"zh": "这个分享已被下架", "en": "This shared board has been taken down."},
    # ---- 统计 ----
    "metric_invalid": {"zh": "不认识的指标:{metric}", "en": "Unknown metric: {metric}"},
    "user_not_found": {"zh": "没有这个用户", "en": "No such user."},
}


def render(code: str, locale: str | None = None, **params: object) -> str:
    entry = MESSAGES.get(code)
    if entry is None:
        return code
    want = locale or current_locale()
    text = entry.get(want) or entry.get(DEFAULT_LOCALE) or code
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return "".join(literal for literal, _, _, _ in Formatter().parse(text) if literal).strip()


class ApiError(Exception):
    """一个给调用方看的错误。`headers` 用于 Retry-After 这类。"""

    def __init__(self, status: int, code: str, *, headers: dict[str, str] | None = None, **params: object) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.params = params
        self.headers = headers or {}

    @classmethod
    def from_format(cls, exc: FormatError, *, status: int = 422, code: str = "invalid_file") -> "ApiError":
        """格式包的校验错误:句子由格式包按此刻的语言说,放进 `detail`。"""
        return cls(status, code, detail=str(exc))

    def payload(self) -> dict[str, dict[str, str]]:
        return {"error": {"code": self.code, "message": render(self.code, None, **self.params)}}


def human_size(size: int) -> str:
    for unit, factor in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if size >= factor:
            value = size / factor
            return f"{value:.0f} {unit}" if value >= 10 or value.is_integer() else f"{value:.1f} {unit}"
    return f"{size} B"


__all__ = ["ApiError", "LOCALES", "MESSAGES", "human_size", "render"]
