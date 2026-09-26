"""智能体调插件工具:**有后果的**先开一张卡(见 domain/effects)。

插件工具在智能体眼里是一个个一等公民(`plugin__<连接>__<工具>`,见 agent.tool_manifest)。此前它们
一律直接跑 —— 只读的该这样,可 Manim 的「自定义动画」是在本机执行一段模型写的 Python,对象存储的
「上传」是把用户的文件传到别人的服务器上,这些和内置的 run_host_code / publish_asset 是同一类事,
却不经任何人点头。现在每个插件工具在清单里声明后果(`effects`),智能体直接调用时:

· none 直接跑(和以前一样,走 routes/agent_tools 那条路);
· paid / external / local-code 开一张**以这个工具的名字**命名的卡,批准之后走同一个 plugins.tools.invoke。

卡以具体的工具名开(而不是一个统称的「运行插件工具」),「本会话始终允许」于是按工具记 ——
允许了一次 Manim 渲染,不等于允许往云盘传文件。这一族名字由 registry.confirmable_family 认领。

用户自己在插件页点「试一下」、工作流里的插件节点、画板上自己点运行,都不经这里:那是人点的。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import fragment
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_family
from app.domain.agent.errors import ConfirmationError
from app.domain.agent.tool_manifest import PLUGIN_TOOL_PREFIX, agent_tool_name
from app.domain.effects import needs_card, permission_for, warning_key

#: 卡上参数那一段最长多少字。完整的参数在卡的载荷里摊开着,这一句只给人扫一眼。
_ARGS_BRIEF_CHARS = 160
_VALUE_BRIEF_CHARS = 40


def exposed_tool(db: Session, name: str, user_id: str | None) -> dict[str, Any] | None:
    """这个人**自己接的**可用连接里,展开名叫 `name` 的那个工具。

    按展开后的名字反查,不把名字劈开拼回 id —— 名字里的非法字符被折成了下划线,拼回去才会错
    (见 agent.tool_manifest.agent_tool_name)。只在他自己的连接里找:否则一个名字对得上的调用
    就会拿着别人的第三方密钥跑起来。
    """
    from app.domain.plugins.tools import exposed

    if not user_id:
        return None
    return next((tool for tool in exposed(db, user_id) if agent_tool_name(tool["instance_id"], tool["name"]) == name), None)


def _brief_value(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        first = text.splitlines()[0] if text else ""
        cut = first[:_VALUE_BRIEF_CHARS]
        return cut + ("…" if len(first) > _VALUE_BRIEF_CHARS or "\n" in text else "")
    dumped = json.dumps(value, ensure_ascii=False)
    return dumped[:_VALUE_BRIEF_CHARS] + ("…" if len(dumped) > _VALUE_BRIEF_CHARS else "")


def brief_arguments(arguments: dict[str, Any]) -> str:
    """参数的一行摘要:`键=值`,长的截断、多行的只留第一行。反引号换掉 —— 摘要按 Markdown 显示。"""
    joined = ", ".join(f"{key}={_brief_value(value)}" for key, value in arguments.items())
    if len(joined) > _ARGS_BRIEF_CHARS:
        joined = joined[:_ARGS_BRIEF_CHARS] + "…"
    return joined.replace("`", "'")


def _bind(name: str) -> ConfirmableTool:
    """展开名 `name` 的那张卡。validate 认的就是这个名字,不是调用方在 payload 里说的。"""

    def validate(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
        """认出是哪个工具、参数够不够,把卡上要说的事实**覆盖**写回 payload。

        effects 决定这次要不要问人、按哪一档问,它不能由调用方在 payload 里自己带 —— 所以 payload 里
        除了参数,别的一律按开卡这一刻的工具重写。
        """
        from app.domain.plugins.errors import PluginDomainError
        from app.domain.plugins.inputs import coerce
        from app.domain.plugins.runtime import PluginRuntimeError, check_required_input

        tool = exposed_tool(db, name, actor)
        if tool is None:
            raise ConfirmationError("confirmErr_pluginToolUnavailable", name=name)
        arguments = payload.get("arguments")
        arguments = {} if arguments is None else arguments
        if not isinstance(arguments, dict):
            raise ConfirmationError("confirmErr_pluginToolBadInput", name=tool["label"], detail="arguments")
        try:
            check_required_input(tool, coerce(tool, arguments))
        except (PluginRuntimeError, PluginDomainError) as exc:
            raise ConfirmationError("confirmErr_pluginToolBadInput", name=tool["label"], detail=str(exc)) from exc
        payload.clear()
        payload.update({
            "arguments": arguments,
            "instance_id": tool["instance_id"],
            "tool_name": tool["name"],
            "tool_label": tool["label"],
            "connection": tool["instance_name"],
            "effects": tool["effects"],
        })

    return ConfirmableTool(
        name=name,
        #: 下限。实际那一档按工具的后果升(escalate);none 的根本不问人(needs_card)。
        permission="edit",
        cost="none",
        summarize=_summarize,
        execute=_execute,
        validate=validate,
        escalate=_escalate,
        needs_card=_needs_card,
    )


def _needs_card(db: Session, payload: dict[str, Any]) -> bool:
    """和画板上的能力同一条(domain/effects):不花钱、不出门的直接跑。

    智能体那条路上 none 的工具根本不开卡(routes/agent_tools 直接跑);能走到这里的 none,是有人
    直接往 /api/confirmations 开了一张 —— 那就照 run_board_item 的做法,卡留痕、不等人。
    """
    return needs_card(payload.get("effects"))


def _escalate(db: Session, tool: str, payload: dict[str, Any]) -> str | None:
    return permission_for(payload.get("effects"))


def _summarize(db: Session, payload: dict[str, Any]) -> Summary:
    arguments = payload.get("arguments") or {}
    brief = brief_arguments(arguments) if isinstance(arguments, dict) and arguments else ""
    warning = warning_key(payload.get("effects"))
    return "confirm_runPluginTool", {
        "tool": str(payload.get("tool_label") or payload.get("tool_name") or ""),
        "connection": str(payload.get("connection") or ""),
        "args": fragment("confirm_pluginToolArgs", args=f"`{brief}`") if brief else "",
        "warning": fragment(warning) if warning else "",
    }


def _execute(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    """批准之后跑:**同一个** plugins.tools.invoke(智能体直接调、工作流节点、插件页试跑走的都是它)。

    只用**批准者自己**接的连接:连接归人,别人批准就是拿接入者的第三方密钥替他花钱 —— 那不是
    批准者能替他决定的。卡开出来之后连接停用了、工具被关了、换了人批,都在这里拒,卡记成失败。
    产出收进这张卡所在的工作区(和其它产素材的工具一样,输出里是 asset_id)。
    """
    from app.domain.plugins.errors import PluginDomainError
    from app.domain.plugins.tools import invoke

    payload = confirmation.payload
    tool = exposed_tool(db, confirmation.tool, actor)
    if tool is None or tool["instance_id"] != payload.get("instance_id") or tool["name"] != payload.get("tool_name"):
        raise ConfirmationError("confirmErr_pluginToolUnavailable", name=confirmation.tool)
    try:
        invocation = invoke(
            db, tool["instance_id"], tool["name"], dict(payload.get("arguments") or {}),
            workspace_id=confirmation.workspace_id,
        )
    except PluginDomainError as exc:
        raise ConfirmationError("confirmErr_pluginToolFailed", name=tool["label"], detail=str(exc)[:400]) from exc
    if invocation.status != "succeeded":
        raise ConfirmationError("confirmErr_pluginToolFailed", name=tool["label"], detail=str(invocation.error or "")[:400])
    output = invocation.output
    return output if isinstance(output, dict) else {"output": output}


confirmable_family(PLUGIN_TOOL_PREFIX, _bind)
