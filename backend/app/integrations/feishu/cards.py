"""飞书交互卡片:让工具确认在飞书里完成,而不是让人切回桌面端。

从飞书驱动智能体、却要切回 Open Studio 点「同意」,这条链路等于只走了一半。所以确认卡直接
发回发起的那个飞书会话,批准/拒绝就地完成。

## 授权:复用已有的账号绑定,不在飞书侧另立一套

点按钮的人按 open_id 走 `_resolve_sender` —— 和发消息完全同一条路径:必须已绑定 Open Studio
账号、且**此刻仍是该工作区成员**。不是发起者也一样要过这关(群里别人点同样要自己有权限),
这正是把授权建立在账号体系上而不是「谁在群里」的意义。

批准还要额外过 `ensure_graph_node_privileges`,且是**按点击者**校验 —— 与 HTTP 路由那边的
规则一致(见 api/routes/confirmations.approve 的注释:卡片是他批的,这次执行记在他头上)。

## 为什么不用存 message_id

卡片回调允许在响应里直接返回一张新卡片,飞书会就地替换原卡。所以「批准后把卡更新成结果态」
不需要我们记住 message_id,也就不必给 ToolConfirmation 加列。
"""

from __future__ import annotations

from typing import Any

# 按钮 value 里带的动作名。飞书把它原样回传,所以这就是回调的路由键。
ACTION_APPROVE = "confirm.approve"
ACTION_REJECT = "confirm.reject"


def _text(content: str) -> dict[str, Any]:
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


def confirmation_card(*, confirmation_id: str, tool: str, summary: str, requested_by: str) -> dict[str, Any]:
    """待确认卡:说清「谁要动什么」,给同意/拒绝两个按钮。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "orange", "title": {"tag": "plain_text", "content": "需要你确认"}},
        "elements": [
            _text(f"**{summary or tool}**"),
            _text(f"工具:`{tool}`\n发起:{requested_by or '智能体'}"),
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "同意"},
                        "type": "primary",
                        "value": {"action": ACTION_APPROVE, "confirmation_id": confirmation_id},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "拒绝"},
                        "type": "danger",
                        "value": {"action": ACTION_REJECT, "confirmation_id": confirmation_id},
                    },
                ],
            },
        ],
    }


def settled_card(*, summary: str, tool: str, decision: str, by: str) -> dict[str, Any]:
    """已决卡:替换掉原卡,**不再带按钮** —— 否则同一张卡会被反复点。"""
    approved = decision == "approved"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "green" if approved else "grey",
            "title": {"tag": "plain_text", "content": "已同意" if approved else "已拒绝"},
        },
        "elements": [
            _text(f"**{summary or tool}**"),
            _text(f"工具:`{tool}`\n{'同意' if approved else '拒绝'}人:{by}"),
        ],
    }


def notice_card(message: str) -> dict[str, Any]:
    """点击被拒时的提示卡(未绑定、无权限、卡已失效)。原卡保持可点,便于有权限的人接手。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "red", "title": {"tag": "plain_text", "content": "无法处理"}},
        "elements": [_text(message)],
    }
