"""What the approval card claims must not understate what approval does."""

from __future__ import annotations

from app.domain.agent.confirmable import tool_spec


class _NoDb:
    """摘要里问库的那几处(工作流的图)在这些用例里问不到东西 —— 给一个什么都查不到的会话,
    断言的是**这句话本身**。"""

    def get(self, _model, _key):
        return None


def _summarize(tool: str, payload: dict, locale: str = "zh") -> str:
    """**渲染之后**再断言 —— 那才是用户在卡上读到的那一行。

    `summarize` 返回的是 (文案 key, 参数),因为这一行会落库而卡活得比一次请求久(见
    confirmable/registry)。断言打在元组上的话,测的是内部表示而不是给人看的结果。
    """
    from app.core.i18n import render_message

    spec = tool_spec(tool)
    assert spec is not None, tool
    key, params = spec.summarize(_NoDb(), payload)
    return render_message(key, locale, params)



def test_a_code_node_is_called_out_in_the_summary() -> None:
    """A `code` node runs arbitrary local Python when the workflow is later run. The summary
    used to render op kinds only — "1 个工作流编辑: add_node" — so the card disclosed nothing
    about the most dangerous thing it could be authorising."""
    summary = _summarize(
        "edit_workflow",
        {"operations": [{"kind": "add_node", "node_type": "code", "config": {"code": "import os"}}]},
    )
    assert "add_node" in summary
    assert "代码节点" in summary, "approving this runs local Python; the card has to say so"


def test_an_ordinary_edit_is_not_dressed_up_as_dangerous() -> None:
    summary = _summarize("edit_workflow", {"operations": [{"kind": "add_node", "node_type": "llm"}]})
    assert "代码节点" not in summary


def test_run_workflow_names_the_workflow() -> None:
    assert "「日更」" in _summarize("run_workflow", {"name": "日更"})
    # Falling back to the id is still better than the bare "运行工作流" it used to render.
    assert "wf-123" in _summarize("run_workflow", {"workflow_id": "wf-123"})


def test_同一张卡英文用户也读得懂() -> None:
    """**确认卡是授权界面** —— 用户点「批准」之前唯一会读的就是这一行。

    此前 23 个摘要返回的都是写死的中文,于是英文用户读到的授权提示永远是中文:
    一个读不懂的授权提示,等于没有提示。而 `Job.message` 早就为同一件事立了规矩
    (落库存 key、出口才翻),确认卡是同一层的另一份给人看的文案,当时没跟着改。
    """
    import re

    cjk = re.compile(r"[一-鿿]")
    cases = [
        ("run_code", {"code": "print(1)"}),
        ("http_request", {"method": "POST", "url": "https://example.com"}),
        ("publish_asset", {"title": "我的视频"}),
        ("run_workflow", {"name": "日更"}),
        ("edit_board", {"operations": [{"kind": "add_card"}]}),
        ("denoise_audio", {"engine_name": "X", "has_strengths": True, "strength": "light"}),
        ("convert_video_to_gif", {"fps": 12, "width": 720, "duration": 3}),
    ]
    for tool, payload in cases:
        english = _summarize(tool, payload, locale="en")
        # 用户自己给的名字(标题、工作流名)当然可以是中文 —— 那是**他的内容**,不是我们的文案。
        ours = cjk.sub("", english.replace("我的视频", "").replace("日更", ""))
        assert ours == english.replace("我的视频", "").replace("日更", ""), (
            f"{tool} 的英文卡里还有中文:{english}"
        )
        assert english.strip(), f"{tool} 的英文卡是空的"
