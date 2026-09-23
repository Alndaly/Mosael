"""棘轮:**接口 out schema 里的每个字段,都要有人读。**

「接口字段 → 前端消费点」这一跳此前没有任何检查,而它**已经在漏**:`WorkspaceSummaryOut`
的 docstring 写着「一次请求给全一屏」—— 它存在的全部理由就是"前端要什么,这里一次给齐" ——
而里面有八个字段在 `frontend/src` 非测试代码里一次都没被读过。最刺眼的一处:「AI 用量」磁贴
显示的是调用次数,而同一个回包里躺着金额和它配套的货币单位,**货币单位被读了,钱数没有**。

多返回几个字段不会让任何东西变红;带默认值的分组字段连"空"都是合法值,后端自己也无从判断
有没有人要。后果不是浪费带宽 —— 是**没人知道这个回包里哪些是界面需要的、哪些是历史残留**,
于是下一个改这页的人既不敢删也不敢信;而那些分组聚合在后端是有成本的,每次打开首页算一遍扔掉。

判据只管 `*Out`:那是后端**交出去**的东西。`*In` / `*Create` 是前端送进来的,"没人读"在那边
是另一个问题(后端不用它),不该混成一条规则。

`NOT_FOR_THE_SCREEN` 是豁免:这些字段的读者不是界面,而是**别的运行时**(MCP 客户端、
agent-sidecar、桌面执行器)或者纯留痕。每条写清读者是谁 —— 一份看得见的清单,而不是散在
各处的既成事实。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OPENAPI = REPO / "backend" / "openapi.json"
GENERATED = REPO / "frontend" / "src" / "api" / "generated" / "schema.d.ts"
FRONTEND = REPO / "frontend" / "src"

#: `"<Schema>.<字段>": "读者是谁"`。读者不是界面的,写在这里。
NOT_FOR_THE_SCREEN: dict[str, str] = {
    # —— 给 MCP 客户端的自述清单(界面不读它,它是给别的智能体看的)
    "AgentManifestOut.openapi_url": "MCP 客户端按它去取 OpenAPI",
    "AgentManifestOut.skills": "MCP 客户端按它决定能调什么",
    # —— 归属与留痕:后端授权按它判,界面拿到的列表已经按人筛过了
    "AgentSessionOut.owner_user_id": "归属由后端判,界面拿到的已经是自己的那些",
    "GenerationSessionOut.owner_user_id": "归属由后端判,界面拿到的已经是自己的那些",
    "ScheduledTaskOut.owner_user_id": "归属由后端判,界面拿到的已经是自己的那些",
    "SessionGroupOut.owner_user_id": "归属由后端判,界面拿到的已经是自己的那些",
    "SessionGroupOut.sort_order": "读者是后端的 ORDER BY:界面**设**它(见 SessionGroupUpdate),拿回来的列表已经排好了",
    "WorkflowRevisionOut.created_by": "留痕:这一版是谁存的",
    "WorkflowRevisionDetailOut.created_by": "留痕:这一版是谁存的",
    "AgentQuestionOut.answered_at": "留痕:什么时候答的",
    "ProviderQuotaOut.fetched_at": "留痕:这份额度是什么时候取的",
    # —— 给 sidecar / MCP 那一侧读的确认卡
    "ConfirmationOut.summary_key": "卡片摘要的未翻译形态。界面读翻好的 summary,这两个给别的运行时",
    "ConfirmationOut.summary_params": "卡片摘要的参数,和 summary_key 一起给别的运行时",
    # —— 凭据租约:sidecar 持有并原样带回,界面不碰
    "LeaseOut.lease": "sidecar 的租约令牌,原样带回给后端",
    # —— 后端/插件宿主内部的指路
    "PluginInstanceOut.package_id": "指向磁盘上的包。界面按实例显示,包是后端的事",
    "PluginToolOut.package_id": "指向磁盘上的包。界面按实例显示,包是后端的事",
    "PluginToolOut.instance_name": "工具清单给智能体看时用它区分同包的多个接入",
    "ProviderModelOut.generation_capability_ref": "生成能力描述符的指针,后端按它查参数表",
    "ProviderModelOut.generation_capabilities_known": "后端据此决定拦不拦未知参数",
    "ProviderPricingRuleOut.effective_from": "计价按时间段生效,算账在后端",
    "ProviderPricingRuleOut.effective_to": "计价按时间段生效,算账在后端",
    "ProviderUsageEventOut.source_type": "这笔账挂在哪类东西上。对账用,不上界面",
    "ProviderUsageEventOut.source_id": "这笔账挂在哪个东西上。对账用,不上界面",
    "ProviderUsageEventOut.raw_usage": "供应商原样回执,留作审计",
    "ProviderUsageEventOut.pricing_rule_id": "这笔按哪条规则算的,对账线索",
    "ScheduledTaskRunOut.scheduled_task_id": "运行记录挂在哪条定时任务上;界面是从那条任务点进来的",
    # —— 一次生成的中间产物,由后端自己接着用
    "SceneReferenceOut.first_frame_asset_id": "生成链路里后端自己接着用的引用",
    "SceneReferenceOut.last_frame_asset_id": "生成链路里后端自己接着用的引用",
    "SceneReferenceOut.video_asset_id": "生成链路里后端自己接着用的引用",
    "SceneReferenceOut.camera_move": "传给生成适配器的镜头运动,后端自己接着用",
    "SceneReferenceOut.skipped_models": "渲染器如实报出跳过了哪些模型,进任务消息而不是这一屏",
    "SceneReferenceOut.model_warnings": "渲染器如实报出的告警,进任务消息而不是这一屏",
    # —— 语音引擎的本地就绪状态,由后端自己判
    "TtsEngineOut.needs_source": "要不要本地权重,后端判",
    "TtsEngineOut.source_ready": "本地权重就绪与否,后端判",
    "TtsEngineOut.source_dir": "本地路径,不该上界面",
    # —— 协作:活动流与评审
    "ActivityOut.actor_id": "界面显示的是 actor 那个对象(名字和头像),原始 id 不上屏",
    "ConfirmationOut.decided_by": "留痕:记在谁头上。界面显示的是哪一档放的,不是一个用户 id",
    #: 下面三条的实情是:**评审这条链在界面上还没有入口** —— `listReviews` / `requestReview` /
    #: `decideReview` 三个客户端函数全仓零调用。它们不是"给别的运行时的",是还没接上的。
    #: 记在这里而不是删掉:接口和后端逻辑都在,缺的是那一屏。
    "ReviewOut.requester": "评审那一屏还没做,整条链在界面上没有入口(见本行上方说明)",
    "ReviewOut.reviewer": "同上:评审那一屏还没做",
    "ReviewOut.decision_note": "同上:评审那一屏还没做",
    "ReviewOut.decided_by": "同上:评审那一屏还没做",
    "ReviewOut.decided_at": "同上:评审那一屏还没做",
    # —— 邀请
    "InvitationOut.invitee_name": "受邀人昵称,发邀请那一侧不显示它",
    "TranscriptTokenOut.token_index": "逐词时间轴里的序号,前端按数组下标走",
}


def _frontend_source() -> str:
    """前端**会读它**的那些源码 —— 生成的类型和测试不算。

    生成的 `schema.d.ts` 里每个字段名都在,拿它当证据等于永远绿;测试里出现一次也不算"界面
    用上了" —— 这两条正是"判据对、扫描面错"的经典长相。
    """
    parts = []
    for path in sorted(FRONTEND.rglob("*.ts*")):
        if ".test." in path.name or "generated" in str(path):
            continue
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _unread() -> dict[str, list[str]]:
    schemas = json.loads(OPENAPI.read_text(encoding="utf-8"))["components"]["schemas"]
    generated = GENERATED.read_text(encoding="utf-8")
    source = _frontend_source()
    found: dict[str, list[str]] = {}
    for name, schema in schemas.items():
        if not name.endswith("Out"):
            continue
        properties = schema.get("properties") or {}
        # 前端生成类型里没有这个 schema = 前端根本拿不到它,不在这条规矩的范围内。
        if not properties or f"{name}:" not in generated:
            continue
        dead = [
            field
            for field in properties
            if not re.search(rf"\b{re.escape(field)}\b", source)
        ]
        if dead:
            found[name] = dead
    return found


def test_扫描面站得住() -> None:
    """前端源码读空了的话,下面那条断言天然成立。"""
    source = _frontend_source()
    assert len(source) > 500_000, f"只读到 {len(source)} 字节前端源码 —— 目录结构变了?"
    assert "usage_cost_micros" in source, "连首页那个字段都搜不到,扫描面坏了"


def test_交出去的每个字段都有人读() -> None:
    orphans = [
        f"{schema}.{field}"
        for schema, fields in sorted(_unread().items())
        for field in fields
        if f"{schema}.{field}" not in NOT_FOR_THE_SCREEN
    ]
    assert not orphans, (
        "这些 out schema 字段前端一次都没读过 —— 后端算它、发它,而没有人要:\n  "
        + "\n  ".join(orphans)
        + "\n要么界面用起来,要么连算带发一起删;确实是给别的运行时(MCP / sidecar / 执行器)"
        "或纯留痕的,写进 NOT_FOR_THE_SCREEN 并说明读者是谁。"
    )


def test_豁免清单里没有已经不存在的字段() -> None:
    """豁免一个已经没了的字段 = 守一个不存在的约定,而且会掩护下一个同名字段。"""
    schemas = json.loads(OPENAPI.read_text(encoding="utf-8"))["components"]["schemas"]
    ghosts = [
        entry
        for entry in sorted(NOT_FOR_THE_SCREEN)
        if entry.split(".", 1)[0] not in schemas
        or entry.split(".", 1)[1] not in (schemas[entry.split(".", 1)[0]].get("properties") or {})
    ]
    assert not ghosts, f"NOT_FOR_THE_SCREEN 里这些字段已经不在接口上了:{ghosts}"


def test_每条豁免都说得出读者是谁() -> None:
    for entry, reader in NOT_FOR_THE_SCREEN.items():
        assert len(reader.strip()) >= 4, f"{entry} 的豁免没写清读者"
