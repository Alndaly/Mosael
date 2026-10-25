"""`domain/feishu/gateway` 的实现:**唯一出网的地方**。

领域那一侧只递语义(哪个机器人、收件 id 与类型、一段文字或一张卡要有什么),飞书的地址、
分页、卡片 JSON 全在这里。`im/v1/messages` / `im/v1/chats` 这两个地址只在 `client` 里出现,
而"谁在用它发消息"只有这一处 —— 加上 `domain/feishu/routing` 的目标解析,就是那句
"发飞书"的**唯一**原语:「等人确认」和 4 个飞书能力节点都从这里走。

登记发生在组装根(`app.main._wire_seams`)—— 和"谁能发确认卡"同一条规矩:领域不认识飞书,
是飞书这一侧把自己接上去。
"""

from __future__ import annotations

from typing import Any

from app.db.models import FeishuBot
from app.domain.feishu import gateway as domain
from app.integrations.feishu import client


def message_card(spec: domain.CardSpec) -> dict[str, Any]:
    """节点要的那种卡片:顶部一句话 + 正文(Markdown)+ 一个可选按钮。

    和确认卡不同,这里的按钮只是**打开一个链接** —— 没有回调、没有决定要落,所以它就是
    飞书卡片上的 `url` 按钮。按钮要么"文案 + 链接"都给,要么都不给(半套按不出来)。
    """
    elements: list[dict[str, Any]] = []
    body = (spec.body or "").strip()
    if body:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": body}})
    link = (spec.link or "").strip()
    label = (spec.button_label or "").strip()
    if link and label:
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {"tag": "button", "text": {"tag": "plain_text", "content": label}, "type": "primary", "width": "fill", "url": link}
                ],
            }
        )
    elif link:
        #: 只给了链接:至少让人点得动它 —— 一个"没有按钮"的链接仍然是信息。
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": link}})
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": spec.title or "Mosael"}},
        "elements": elements,
    }


class FeishuTransport:
    """`domain.feishu.gateway.Transport` 的那一份实现。方法都只是把语义交给 `client`。"""

    def send_text(self, bot: FeishuBot, receive_id: str, receive_type: str, text: str) -> str:
        return client.send_text(bot, receive_id, text, receive_id_type=receive_type)

    def send_card(self, bot: FeishuBot, receive_id: str, receive_type: str, card: dict[str, Any]) -> str:
        return client.send_card(bot, receive_id, card, receive_id_type=receive_type)

    def update_card(self, bot: FeishuBot, message_id: str, card: dict[str, Any]) -> None:
        #: **就地换掉**(消息 id 不变):取消 / 超时之后把群里那张卡收回成结果态,别人不必再点。
        client.update_card(bot, message_id, card)

    def card(self, spec: domain.CardSpec) -> dict[str, Any]:
        return message_card(spec)

    def download(self, bot: FeishuBot, message_id: str, file_key: str, kind: str) -> domain.Downloaded:
        got = client.download_message_resource_named(bot, message_id, file_key, kind)
        return domain.Downloaded(data=got.data, filename=got.filename, content_type=got.content_type)

    def add_reaction(self, bot: FeishuBot, message_id: str, emoji_type: str) -> str:
        #: **严格那一份**:节点加不上表情要算失败(见 client.add_reaction_strict)。
        return client.add_reaction_strict(bot, message_id, emoji_type)

    def chats(self, bot: FeishuBot, *, limit: int = 200) -> list[dict[str, str]]:
        return client.list_chats(bot, limit=limit)


TRANSPORT = FeishuTransport()
