"""飞书交互卡片:让工具确认在飞书里完成,而不是让人切回桌面端。

从飞书驱动智能体、却要切回 Mosael 点「同意」,这条链路等于只走了一半。所以确认卡直接
发回发起的那个飞书会话,批准/拒绝就地完成。

## 授权:复用已有的账号绑定,不在飞书侧另立一套

点按钮的人按 open_id 走 `_resolve_sender` —— 和发消息完全同一条路径:必须已绑定 Mosael
账号、且**此刻仍是该工作区成员**。不是发起者也一样要过这关(群里别人点同样要自己有权限),
这正是把授权建立在账号体系上而不是「谁在群里」的意义。

批准走的是与 HTTP 路由**同一个** `authorize_and_approve`,且**按点击者**校验:卡片是他批的,
这次执行就记在他头上(见 domain/agent/confirmations 与 tests/test_agent_identity_ratchet.py)。

## 消息 id:回调响应优先,消息 id 兜底

批准时的回调响应可以就地换卡,这是最快的一条路;但它有 2.5 秒预算,超时后响应会被丢掉。
应用内批准 / 过期也没有回调可搭车。所以工具确认卡和问题卡都保存 `feishu_message_id`:
回调响应能到就响应,到不了(或不是从卡片触发)就用 `PATCH im/v1/messages/:message_id`
把原卡收回成结果态。工作流确认卡原本就存这一格(ADR 0069)。

**不存在“不用存”的卡片了。** 没有消息 id 时只能让旧卡继续可点,用户第二次点才得到
“已经处理过了” —— 这是一句误导,不是结果。
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


def _button_row(buttons: list[dict[str, Any]]) -> dict[str, Any]:
    """同一行的按钮等宽铺满;按钮自身再 `fill`,不在右侧留空白。

    `bisect` 让两个 column 等宽,`width: fill` 让按钮填满自己的 column。form 里的
    `name` / `action_type` 原样保留,不改提交语义。
    """
    return {
        "tag": "column_set",
        "flex_mode": "bisect" if len(buttons) > 1 else "none",
        "horizontal_spacing": "default",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "vertical_align": "top",
                "elements": [{**button, "width": "fill"}],
            }
            for button in buttons
        ],
    }


def confirmation_card(*, confirmation_id: str, tool: str, summary: str, requested_by: str) -> dict[str, Any]:
    """待确认卡:说清「谁要动什么」,给同意/拒绝两个按钮。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "orange", "title": {"tag": "plain_text", "content": "需要你确认"}},
        "elements": [
            _text(f"**{summary or tool}**"),
            _text(f"工具:`{tool}`\n发起:{requested_by or '智能体'}"),
            _button_row([
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
            ]),
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


def expired_card(*, summary: str, tool: str) -> dict[str, Any]:
    """这张卡已经因为对话结束 / 等待超时 / 重启而作废,不能再点。"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "grey", "title": {"tag": "plain_text", "content": "已失效"}},
        "elements": [
            _text(f"**{summary or tool}**"),
            _text("这一轮已经结束,这张卡不能再操作。"),
        ],
    }


def interrupted_card(*, summary: str, tool: str) -> dict[str, Any]:
    """这张卡**批过、也已经开始执行**,但后端在它落结果之前重启了 —— 结果是「不知道」。

    不能写「已同意」:那读起来像已经做完了。也不能写「已失效」:那读起来像没做。所以单独一副说法,
    并且明说**先去确认,别直接重做** —— 它可能已经生效了一半(见 domain/agent/card_expiry 的 UNKNOWN)。
    """
    return {
        "config": {"wide_screen_mode": True},
        "header": {"template": "orange", "title": {"tag": "plain_text", "content": "结果未知"}},
        "elements": [
            _text(f"**{summary or tool}**"),
            _text("这张卡已经批准,但后端在它执行时重启了 —— 动作可能已经生效,也可能没有。先确认现状,不要直接重做。"),
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
    buttons = [
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
    ]
    if allow_note:
        #: **有输入框时,按钮必须在这个 form 里面,并且是 `form_submit`。**
        #: 飞书对卡片 schema 是硬校验:form 里没有一个提交按钮,整张卡直接不收 ——
        #: 真实错误码(从 `feishu_delivery_reason` 里读到的):
        #:   `ErrCode: 300123, ErrPath: ROOT -> elements -> [3](tag: form),`
        #:   `ErrMsg: there is no submit button in the form container`
        #: 于是"为了能带一句备注"加的输入框,把整张卡连带拒掉了,只剩降级的那段文字。
        #: 现在按钮就在 form 里(带 `value` 区分同意/拒绝),备注与决定一起提交。
        elements.append({
            "tag": "form",
            "name": "approval_note",
            "elements": [
                {
                    "tag": "input",
                    "name": NOTE_FIELD,
                    "width": "fill",
                    "placeholder": {"tag": "plain_text", "content": "备注(可留空)"},
                },
                _button_row([
                    {
                        **button,
                        "action_type": "form_submit",
                        "name": button["value"]["action"].rsplit(".", 1)[-1],
                    }
                    for button in buttons
                ]),
            ],
        })
    else:
        elements.append(_button_row(buttons))
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
