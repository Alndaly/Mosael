"""社区这一侧说「不行」的几种情形。都带文案 key,按请求方的语言翻;`http_status` 是路由翻成 HTTP 时用的码。

**没有一种会翻成 401**:前端把本机后端回的 401 当成「本机登录过期」、直接退回登录页。社区账号掉线是另一件事,
用 409 + 一句「社区账号已退出,请重新连接」说。
"""

from __future__ import annotations

from app.core.i18n import LocalizedError


class CommunityError(LocalizedError, ValueError):
    """社区相关的操作做不成。"""

    http_status = 422


class NotConfigured(CommunityError):
    """这台部署没配社区地址(部署设置里清空了)。"""

    http_status = 409

    def __init__(self) -> None:
        super().__init__("communityErr_notConfigured")


class NotConnected(CommunityError):
    """这个人还没连社区账号。"""

    http_status = 409

    def __init__(self) -> None:
        super().__init__("communityErr_notConnected")


class SignedOut(CommunityError):
    """刷新令牌被吊销(网页「设备」页里撤了、被判定为盗用、过期)或刷新之后仍然 401 —— 本机存的令牌已经删掉。"""

    http_status = 409

    def __init__(self) -> None:
        super().__init__("communityErr_signedOut")


class Unreachable(CommunityError):
    """连不上社区服务(网络、超时、对方 5xx)。**不动存着的令牌** —— 连不上不等于被退出。"""

    http_status = 502

    def __init__(self, detail: str) -> None:
        super().__init__("communityErr_unreachable", detail=detail)


class Rejected(CommunityError):
    """社区服务明确拒绝了这一次请求(校验不过、没有权限、不存在)。`message` 是对方按请求语言给的原话。"""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__("communityErr_rejected", status=status, message=message or code)
        self.status = status
        self.code = code
        self.http_status = 404 if status == 404 else 409 if status in (403, 409) else 422


class TooLarge(CommunityError):
    """快照超出限额(格子数、单个文件、总大小)。在上传之前就拦下,说清是哪一条。"""

    http_status = 422
