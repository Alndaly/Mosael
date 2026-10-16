"""飞书交互卡片:让工具确认在飞书里完成,而不是让人切回桌面端。

从飞书驱动智能体、却要切回 Mosael 点「同意」,这条链路等于只走了一半。所以确认卡直接
发回发起的那个飞书会话,批准/拒绝就地完成。

## 授权:复用已有的账号绑定,不在飞书侧另立一套

点按钮的人按 open_id 走 `_resolve_sender` —— 和发消息完全同一条路径:必须已绑定 Mosael
账号、且**此刻仍是该工作区成员**。不是发起者也一样要过这关(群里别人点同样要自己有权限),
这正是把授权建立在账号体系上而不是「谁在群里」的意义。

批准走的是与 HTTP 路由**同一个** `authorize_and_approve`,且**按点击者**校验:卡片是他批的,
这次执行就记在他头上(见 domain/agent/confirmations 与 tests/test_agent_identity_ratchet.py)。

## 为什么不用存 message_id

卡片回调允许在响应里直接返回一张新卡片,飞书会就地替换原卡。所以「批准后把卡更新成结果态」
不需要我们记住 message_id,也就不必给 ToolConfirmation 加列。
"""

from __future__ import annotations

from typing import Any

# 按钮 value 里带的动作名。飞书把它原样回传,所以这就是回调的路由键。
ACTION_APPROVE = "confirm.approve"
ACTION_REJECT = "confirm.reject"
#: 工作流「等人确认」那张卡的按钮。和工具确认卡共用一个入口(handle_card_action),
#: 靠**动作名前缀**分流 —— 两件事的决定落在两张不同的单上,但它们走的是同一条回调线。
ACTION_RUN_APPROVE = "workflow.approve"
ACTION_RUN_REJECT = "workflow.reject"
#: 卡片上那个备注输入框的名字。飞书把表单里填的值回传在 `value` 里(见 worker.card_action)。
NOTE_FIELD = "note"


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


# ---------------- 工作流「等人确认」 ----------------
#
# 和工具确认卡同一个形状(同一处回调、同一条授权、同样靠响应里的新卡片就地替换),但决定落的是
# **工作流那次运行**的那张待批单(见 domain/workflows/approvals)。文案由节点给(标题、正文、
# 按钮上写什么),这里只负责把它摆成一张卡 —— 节点作者说的话不该被卡片模板改写。


def approval_card(
    *, approval_id: str, title: str, body: str, workflow: str, node: str,
    approve_label: str, reject_label: str, allow_note: bool, timeout_hours: int | None,
) -> dict[str, Any]:
    """待确认卡:节点给的标题 / 正文 / 按钮文案,加一格备注输入框(节点说不要就没有)。"""
    elements: list[dict[str, Any]] = [_text(body)] if body.strip() else []
    elements.append(_text(f"工作流:`{workflow}` · 节点:`{node}`"))
    if timeout_hours:
        elements.append(_text(f"超过 **{timeout_hours} 小时**没人处理就按节点上写的办。"))
    if allow_note:
        #: 输入框留给批的人写一句话。**按钮照旧是普通按钮(`value` 里带着动作)** —— 不指望
        #: 表单提交把输入框的值带回来:带得回来就用(见 approvals._note_from),带不回来这一步也
        #: 照样批得动。一个收不到备注的输入框是可接受的退化,一个点不动的按钮不是。
        elements.append({
            "tag": "form",
            "name": "approval_note",
            "elements": [{
                "tag": "input",
                "name": NOTE_FIELD,
                "placeholder": {"tag": "plain_text", "content": "备注(可留空)"},
            }],
        })
    elements.append({
        "tag": "action",
        "actions": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": approve_label or "确认"},
                "type": "primary",
                "value": {"action": ACTION_RUN_APPROVE, "approval_id": approval_id},
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": reject_label or "拒绝"},
                "type": "danger",
                "value": {"action": ACTION_RUN_REJECT, "approval_id": approval_id},
            },
        ],
    })
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "orange", "title": {"tag": "plain_text", "content": title or "需要你确认"}},
        "elements": elements,
    }


def settled_approval_card(*, title: str, decision: str, by: str, note: str) -> dict[str, Any]:
    """已决卡:替换掉原卡,**不再带按钮**(否则同一张卡会被反复点),并写上是谁批的、有没有备注。"""
    approved = decision == "approved"
    cancelled = decision == "cancelled"
    timed_out = decision == "timeout"
    heading = "已确认" if approved else ("已拒绝" if not timed_out else "超时")
    if cancelled:
        heading = "已取消"
    template = "green" if approved else ("grey" if not timed_out else "orange")
    who = f"\n决定人:{by}" if by else ""
    tail = f"\n备注:{note}" if note.strip() else ""
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": template, "title": {"tag": "plain_text", "content": heading}},
        "elements": [_text(f"**{title}**{who}{tail}")],
    }
