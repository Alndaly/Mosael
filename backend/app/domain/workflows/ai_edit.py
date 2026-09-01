"""智能体图编辑:自然语言指令 → 修改后的工作流 graph。

经自动化执行面调用 LLM(无智能体工具,确定性强):提示词带上节点类型注册表
与当前 graph,要求只输出 JSON;返回前必须过 validate_graph,失败会把
错误喂回去重试一次。
"""

from __future__ import annotations

import json
from typing import Any


from sqlalchemy.orm import Session

from app.domain.ai_chat import AiChatError, ChatTarget, chat, target_for
from app.domain.usage import BillableCall, billable
from app.domain.providers import require_connection
from app.domain.workflows import NODE_TYPES, WorkflowDomainError, validate_graph

TIMEOUT_SECONDS = 120

_SYSTEM = """你是 Open Studio 视频创作工作台的工作流编辑器。工作流是一个 DAG:
{"nodes": [{"id", "type", "name", "position": {"x", "y"}, "config"}], "edges": [{"id", "source", "target"}]}

可用节点类型(config 字段与输出见注册表):
%s

规则:
1. 必须恰好一个 start 节点;图必须无环;连线两端必须存在。
2. 节点 config 的字符串值可用 {{节点id.输出名}} 引用上游输出;start 的参数用 {{start.参数名}}。
3. 布局:position 从左到右按执行顺序排,x 间隔约 240,y 错开避免重叠。
4. 保留用户没让你改的部分(包括节点 id 与 position),新增节点用短的语义化 id。
5. 只输出一个 JSON 对象,不要任何解释文字、不要代码块围栏,格式:
   {"graph": {...}, "summary": "一句话说明改了什么"}
"""


def ai_edit_graph(
    db: Session,
    *,
    instruction: str,
    graph: dict[str, Any],
    profile_id: str | None = None,
    workspace_id: str = "",
    workflow_id: str = "",
    user_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    profile = require_connection(db, profile_id, user_id=user_id, error=WorkflowDomainError)
    try:
        target = target_for(db, profile, surface="automation")
    except AiChatError as exc:
        raise WorkflowDomainError(str(exc)) from exc
    registry = json.dumps(
        {key: {"label": meta["label"], "config": meta["config"], "outputs": meta["outputs"]} for key, meta in NODE_TYPES.items()},
        ensure_ascii=False,
    )
    system = _SYSTEM % registry
    user = f"当前工作流 graph:\n{json.dumps(graph, ensure_ascii=False)}\n\n用户指令:{instruction}"

    # 重试循环整体算**一次** AI 编排:两次 HTTP 是同一件事的两次尝试,token 累加成一条账,
    # 而不是让用户在成本明细里看到两行不明所以的记录。
    with billable(
        db,
        capability="chat",
        operation="workflow_ai_edit",
        workspace_id=workspace_id,
        source_type="workflow",
        source_id=workflow_id,
    ) as call:
        last_error = ""
        for _attempt in range(2):
            prompt = user if not last_error else f"{user}\n\n你上次的输出未通过校验:{last_error}\n请修正后重新输出。"
            raw = _chat(target, system, prompt, call)
            try:
                payload = _parse_json(raw)
                new_graph = payload["graph"]
            except (KeyError, ValueError) as exc:
                last_error = f"JSON 解析失败: {exc}"
                continue
            errors = validate_graph(new_graph, require_config=False)
            if errors:
                last_error = "；".join(errors)
                continue
            return new_graph, str(payload.get("summary", ""))
        raise WorkflowDomainError(f"AI 未能产出合法的工作流: {last_error}")


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("输出中没有 JSON 对象")
    return json.loads(text[start : end + 1])


def _chat(target: ChatTarget, system: str, user: str, call: BillableCall | None = None) -> str:
    try:
        return chat(
            target,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
            timeout=TIMEOUT_SECONDS,
            call=call,
            label="AI 编排",
        )
    except AiChatError as exc:
        raise WorkflowDomainError(str(exc)) from exc
