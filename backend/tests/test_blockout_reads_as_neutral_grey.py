"""白模只交代形状、机位和站位,不交代气氛(ADR 0097 修订三)。

此前规则把背景写死成近黑的 "#20242c"、灯光按视觉圣经的夜色压暗,模型又把墙面、地面挑成深蓝灰:《长明灯》第 1 场的
白模渲出来几乎一片黑,形状看不出来,画关键帧的模型只好照着场景设定图的构图画。整片的「设计 3D 白模布景与机位」和画板上
「按文字搭 3D 场景」读同一份规则,两处都钉住。"""

from __future__ import annotations

from app.domain.workflows.templates.blockout import blockout_rules, single_set_rules


def test_两种搭法都要中性灰_浅背景_只取光的方向() -> None:
    for rules in (blockout_rules(5, source="视觉圣经"), single_set_rules(5, source="这段文字")):
        assert '"#c8c8c8"' in rules and '"#9a9a9a"' in rules and '"#6e6e6e"' in rules
        assert 'background 写 "#b8bcc2"' in rules and "ambient 写 2.5" in rules
        assert "不调暗、不上色" in rules
        assert "#20242c" not in rules
