"""翻译节点的「引擎」说明要和实际的默认一致。

留空时不是固定走 Google:执行器把空引擎交给 capabilities.pick,按运行者在设置里定的默认翻译挑,
没定过才落到 Google 免费翻译。此前说明写的是「默认 Google 免费」—— 定过默认的人照着它以为留空
就是 Google,实际跑的是自己设的那一家(可能是要花钱的对话模型)。
"""

from __future__ import annotations

import pytest

from tests.util import fresh_client


@pytest.mark.parametrize("node_type", ["translate", "translate_lines"])
@pytest.mark.parametrize(("locale", "settings_word", "wrong"), [("zh-CN", "设置", "默认 Google"), ("en-US", "Settings", "by default")])
def test_留空按设置里的默认说_不说默认是Google(node_type: str, locale: str, settings_word: str, wrong: str) -> None:
    client = fresh_client()
    types = client.get("/api/workflows/node-types", headers={"Accept-Language": locale}).json()
    engine = next(one for one in types if one["type"] == node_type)["config"]["engine"]
    description = engine["description"]
    assert settings_word in description
    assert wrong not in description
