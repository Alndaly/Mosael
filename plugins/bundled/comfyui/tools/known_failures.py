"""认得出的 ComfyUI 执行错误:原话里带着这一段,就说清「为什么」和「怎么修」(宿主摆在失败卡上那句话下面)。

只收**确定**的那几种:原话里那一段指着一个已知的原因,修法也是确定的。认不出的不猜 —— 失败卡上照样有那句话和原文。
加一种就在 `KNOWN` 里加一条:`pattern` 匹配 ComfyUI 的原话(`exception_message`,不分大小写),`cause` 是一句原因,
`steps` 是修的步骤 —— 要在终端里敲的命令单独放进 `command`(宿主用等宽字摆成一块、带复制),别埋在句子里。

交给宿主的形状(失败的样子里的 `hint`,见 docs/PLUGIN_MANIFEST「失败的样子」)由 `fix` 拼:
`{"cause": {zh, en}, "steps": [{"text": {zh, en}, "command": "…"}]}`,两格都可以没有,但至少有一格。
"""

from __future__ import annotations

import re
from typing import Any, NamedTuple


class Step(NamedTuple):
    """修的一步:一句话(两种语言),要敲的命令另放(原样照抄,不翻)。"""

    text: dict[str, str]
    command: str = ""


class Known(NamedTuple):
    pattern: re.Pattern[str]
    cause: dict[str, str]
    steps: tuple[Step, ...]


KNOWN: tuple[Known, ...] = (
    #: comfy-kitchen 的 hostbuf 读文件那一步,老版本在新的 ComfyUI 上读模型就报这一句(和工作流无关,换哪张图都一样)。
    Known(
        re.compile(r"hostbuf_file_reader_read failed", re.IGNORECASE),
        {
            "zh": "那台 ComfyUI 装的 comfy-kitchen 或 comfyui-workflow-templates 太旧,读不了模型文件 —— 不是这张工作流的问题,换哪张都一样。",
            "en": "That ComfyUI install has an old comfy-kitchen or comfyui-workflow-templates that can't read model files. "
                  "It isn't this workflow: every workflow fails the same way.",
        },
        (
            Step(
                {
                    "zh": "在那台机器上,用 ComfyUI 自己的那个 Python 环境把两个包升上去(comfy-kitchen 要 0.2.37 以上、"
                          "comfyui-workflow-templates 要 0.11.77 以上):",
                    "en": "On that machine, upgrade both packages in the Python environment ComfyUI runs on (comfy-kitchen 0.2.37 "
                          "or later, comfyui-workflow-templates 0.11.77 or later):",
                },
                'pip install -U "comfy-kitchen>=0.2.37" "comfyui-workflow-templates>=0.11.77"',
            ),
            Step({"zh": "重启 ComfyUI,再生成一次。", "en": "Restart ComfyUI and generate again."}),
        ),
    ),
)


def fix(cause: dict[str, str] | None, steps: tuple[Step, ...] | list[Step] = ()) -> dict[str, Any]:
    """一句原因加几步修法 → 失败的样子里的 `hint`。"""
    return {
        **({"cause": dict(cause)} if cause else {}),
        **({"steps": [{"text": dict(one.text), **({"command": one.command} if one.command else {})} for one in steps]}
           if steps else {}),
    }


def hint_for(said: str) -> dict[str, Any] | None:
    """ComfyUI 的原话 → 认得出就是那份「原因 + 怎么修」,认不出是 None。"""
    for one in KNOWN:
        if one.pattern.search(said or ""):
            return fix(one.cause, one.steps)
    return None


__all__ = ["KNOWN", "Known", "Step", "fix", "hint_for"]
