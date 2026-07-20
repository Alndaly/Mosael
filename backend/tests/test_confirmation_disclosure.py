"""What the approval card claims must not understate what approval does."""

from __future__ import annotations

from app.domain.agent.confirmations import _summarize


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
