"""飞书的外部能力:发文字 / 发卡片 / 取附件 / 加表情 / 列群。

## 为什么这里只有一道缝,没有实现

**领域层不认识集成层**(tests/test_import_layering 连函数内的延迟导入都不放过)。而两族节点要的是
同一套"发飞书":「等人确认」(`await_approval`)和 4 个飞书能力节点。真正出网的那一份住在
`app/integrations/feishu`(地址、分页、卡片 JSON 全在那儿),这一处是那道缝 ——
组装根(`app.main._wire_seams`)把实现登记进来,领域只认"有人会替我发"。

**一次调用都不许各写一套**:目标解析在 `domain/feishu/routing`,发送在这里,
两者合起来就是那句"发飞书"的原语。谁绕过它自己拼地址、自己挑机器人,就是把同一个答案写成两份。

登记的实现可以是任何满足 `Transport` 的东西 —— 测试里换一份就能把出网整段掐掉。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.i18n import LocalizedError
from app.db.models import FeishuBot


class FeishuUnavailable(LocalizedError, RuntimeError):
    """这套运行环境没装上飞书那一半(组装根没登记实现)。

    这不是"飞书那边出错了",而是**这一侧没有接上** —— 所以它不降级、直接说清:
    让一个"发飞书"的节点以为发成功了,比失败糟得多。
    """


@dataclass(frozen=True)
class CardSpec:
    """一张卡片的**语义**:顶部那句话、正文、一个可选按钮。

    飞书那套卡片 JSON 的形状是集成层的事(见 integrations/feishu/gateway.message_card)——
    领域只说"这张卡上要有什么",不说它长什么样。
    """

    title: str = ""
    body: str = ""
    link: str = ""
    button_label: str = ""


@dataclass(frozen=True)
class Downloaded:
    """取回来的一份资源:字节、它叫什么、是什么类型。"""

    data: bytes
    filename: str
    content_type: str


class Transport(Protocol):
    """出网那一侧要说得出的话。每一条都返回/接受**领域**能理解的东西。"""

    def send_text(self, bot: FeishuBot, receive_id: str, receive_type: str, text: str) -> str: ...

    def send_card(self, bot: FeishuBot, receive_id: str, receive_type: str, card: dict) -> str: ...

    def update_card(self, bot: FeishuBot, message_id: str, card: dict) -> None:
        """**就地换掉**一条已经发出去的交互卡片:消息 id 不变,内容换成另一张。

        「等人确认」用它把群里那张卡收回成结果态(取消 / 超时之后不留一张还能点的死卡)。
        飞书只让改"自己发的、而且是交互卡片"的消息 —— 降级发出去的那种纯文字消息改不了,
        调用方据此再补一条(见 integrations/feishu/approvals.settle_run_approval)。
        """
        ...

    def card(self, spec: CardSpec) -> dict: ...

    def download(self, bot: FeishuBot, message_id: str, file_key: str, kind: str) -> Downloaded: ...

    def add_reaction(self, bot: FeishuBot, message_id: str, emoji_type: str) -> str: ...

    def chats(self, bot: FeishuBot, *, limit: int = 200) -> list[dict[str, str]]: ...


_TRANSPORT: Transport | None = None


def use_transport(transport: Transport) -> None:
    """登记"怎么发飞书"。组装根调(app.main._wire_seams),别处不该调。"""
    global _TRANSPORT
    _TRANSPORT = transport


def transport() -> Transport:
    """拿这套系统登记的那一份实现;没登记就是没接飞书。"""
    if _TRANSPORT is None:
        raise FeishuUnavailable("wfErr_feishuNotWired")
    return _TRANSPORT


def wired() -> bool:
    """飞书这一半接上了没有。选择器那几处据此决定是问清单还是给空表。"""
    return _TRANSPORT is not None
