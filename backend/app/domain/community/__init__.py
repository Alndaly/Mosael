"""社区服务的客户端(ADR 0026 阶段 3、4 的应用这一半)。

- `accounts` —— 社区账号:刷新令牌落盘加密、访问令牌在内存,`CommunityClient` 负责提前续期、401 续一次重放
  一次、同一个人同一时刻只有一个续期在飞;
- `device` —— 连账号:设备授权(RFC 8628)的发起与节流轮询;
- `snapshot` —— 画板 → `mosael.board-snapshot/1`(白名单字段、媒体换成内容哈希、限额);
- `shares` —— 画板分享:三步上传(去重、续传)作为一个任务,以及改设置、撤回;
- `publish` —— 「发布到社区」:工作流(新条目 / 新版本)与插件(打包、自检、上传);
- `transport` —— 地址怎么拼、错误体怎么读、HTTP 客户端从哪来。

社区服务本身在 `community/`(另一个进程、另一台机器),这里只是它的一个客户端。
"""

from app.domain.community.errors import (
    CommunityError,
    NotConfigured,
    NotConnected,
    Rejected,
    SignedOut,
    TooLarge,
    Unreachable,
)

__all__ = [
    "CommunityError",
    "NotConfigured",
    "NotConnected",
    "Rejected",
    "SignedOut",
    "TooLarge",
    "Unreachable",
]
