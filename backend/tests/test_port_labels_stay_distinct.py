"""同一个节点上两个口不叫同一个名字:内置节点靠声明本身,插件节点由目录出口兜底。

现场:「AI 生成素材」的输出口在中文界面上是 素材 / 素材 / 生成任务 —— 封面那一份(asset_id)和这次出的全部
(asset_ids)都翻成「素材」;英文界面上「取资产」一类节点的 asset_id 和 entity_id 都叫 Asset。画布上两个一模一样的口,
连线的人只能挨个试。

- 内置节点:每种语言里,同一个节点的输出名、字段名两两不同 —— **不靠兜底**,兜底的「名字(键)」是给插件的;
- 插件节点:作者给两个输出写了同一个名字,目录出口在后面带上各自的键(node_catalog.distinct_labels);
- 引用在一句话里怎么说(reference_label)和画布上的口同名:「输出」节点的每一项具名输出叫它自己的键。

画布那一侧(每个口按界面语言叫什么、官方模板里一个都不漏)见 frontend/src/features/workflows/portsHaveHumanNames.test.ts。
"""

from __future__ import annotations

import pytest

from app.core.i18n import t
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.node_catalog import describe_node_types, distinct_labels
from app.domain.workflows.node_types import config_label, output_label, reference_label


@pytest.mark.parametrize("locale", ["zh", "en"])
def test_built_in_nodes_never_need_the_fallback(locale: str) -> None:
    clashes = []
    for node_type, meta in NODE_TYPES.items():
        outputs = [t(output_label(output, meta), locale) for output in meta["outputs"]]
        fields = [t(config_label(key, spec), locale) for key, spec in meta["config"].items()]
        for side, labels in (("输出", outputs), ("字段", fields)):
            repeated = sorted({label for label in labels if labels.count(label) > 1})
            if repeated:
                clashes.append(f"{node_type} 的{side}:{repeated}")
    assert clashes == []


def test_the_asset_pair_reads_differently_in_both_languages() -> None:
    meta = NODE_TYPES["ai_generate"]
    for locale in ("zh", "en"):
        single, many = (t(output_label(key, meta), locale) for key in ("asset_id", "asset_ids"))
        assert single != many
    #: 英文界面上素材是 Media(和导航「Media」一致),资产才是 Asset。
    assert t(output_label("asset_id", meta), "en") == "Media"
    assert t(output_label("entity_id", NODE_TYPES["entity_get"]), "en") == "Asset"


def test_a_plugin_that_names_two_outputs_alike_gets_them_told_apart() -> None:
    plugin = {
        "plugin.demo.render": {
            "label": "渲染",
            "description": "",
            "category": "wfCat_plugin",
            "config": {
                "title": {"type": "template", "label": "标题"},
                "heading": {"type": "template", "label": "标题"},
            },
            "outputs": ["artifact", "preview"],
            "output_labels": {"artifact": "成品", "preview": "成品"},
        }
    }
    [described] = describe_node_types(plugin, "zh")
    assert described["output_labels"] == {"artifact": "成品(artifact)", "preview": "成品(preview)"}
    assert {key: spec["label"] for key, spec in described["config"].items()} == {
        "title": "标题(title)",
        "heading": "标题(heading)",
    }


def test_distinct_labels_leaves_unique_names_alone() -> None:
    assert distinct_labels({"a": "甲", "b": "乙"}) == {"a": "甲", "b": "乙"}


def test_a_named_output_is_called_by_its_own_key_in_sentences() -> None:
    nodes = {"deliver": {"id": "deliver", "type": "output", "name": "交付", "config": {"values": {"note_id": "x"}}}}
    assert reference_label(["deliver", "output", "note_id"], nodes) == "交付 · note_id"
    #: 整个对外输出(不点名哪一项)照旧叫目录给的名字。
    assert reference_label(["deliver", "output"], nodes) != "交付 · output"
