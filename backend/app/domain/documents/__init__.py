"""文档(ADR 0031):素材库里的 PDF / Office / 文本文件,解析成 Markdown 给人和智能体读。

解析是一项**宿主能力** `document_parse`:宿主自带本地解析(`builtin:local`,纯 Python 库,本机装了 LibreOffice
时 Office 文档也渲页面图),插件(MinerU 等)声明 `provides: ["document_parse"]` 做别的实现。挑哪一家是
domain/capabilities 那一份挑法:**没定默认就用本地的** —— 文档是用户的原件,交给云端解析必须是他自己定过的
(`auto_single=False`:装了 MinerU 也不会悄悄替他把文档传上去)。
"""

from __future__ import annotations

from app.domain.capabilities import Builtin, Capability, CapabilityUnavailable
from app.domain.plugins.manifest import DOCUMENT_PARSE
LOCAL_PARSER = "builtin:local"


class DocumentParserUnavailable(CapabilityUnavailable):
    """定下的解析插件用不了(没配好、太旧)。消息说清下一步。"""


CAPABILITY = Capability(
    name=DOCUMENT_PARSE,
    label_key="capability_document_parse",
    description_key="capability_document_parse_desc",
    error=DocumentParserUnavailable,
    none_key="docErr_noParser",
    incomplete_key="docErr_parserIncomplete",
    ambiguous_key="docErr_parserAmbiguous",
    outdated_key="docErr_parserOutdated",
    builtin=Builtin(id=LOCAL_PARSER, name_key="docParser_local"),
    auto_single=False,
)

__all__ = ["CAPABILITY", "DOCUMENT_PARSE", "LOCAL_PARSER", "DocumentParserUnavailable"]
