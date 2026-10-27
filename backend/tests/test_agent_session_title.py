"""新会话的标题取用户敲的那句话 —— 附件标记、文本附件的围栏块是发送时拼上去的,不算。

此前标题直接截首条消息前 60 个字:挂了一份 PDF 的会话在标题栏里叫
「分析一下这个协议 [附件 asset_id=3884… 名称=YS」。
"""

from __future__ import annotations

from app.domain.agent.prompt import session_title


def test_附件标记不进标题() -> None:
    content = "分析一下这个协议\n[附件 asset_id=388447866038 名称=YS区域租赁协议.pdf 类型=document]"
    assert session_title(content) == "分析一下这个协议"


def test_文本附件的围栏块不进标题() -> None:
    content = "总结一下\n\n[已附加 notes.txt]\n```\n第一行\n第二行\n```"
    assert session_title(content) == "总结一下"


def test_只发了附件就用附件名() -> None:
    assert session_title("[附件 asset_id=a1 名称=季度 报告.pdf 类型=document]") == "季度 报告.pdf"


def test_超长截到上限() -> None:
    assert len(session_title("字" * 200)) == 60
