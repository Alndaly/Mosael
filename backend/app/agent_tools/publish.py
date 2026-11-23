"""发布:发出去、看账号、看任务。

从仓库根的 mcp_server.py 按工具族拆出来(架构体检第 8 条)。登记、调用身份、领域用例的调用方式见 ./registry。
"""

from __future__ import annotations

from typing import Any

from app.agent_tools.registry import confirmation_reply, default_workspace_id, open_card, REQUESTED_BY, tool, use_case
from app.api.schemas import PublishAccountOut, PublishTaskOut
from app.domain.publish import use_cases as publish_uc

@tool(effect="confirms")
def publish_asset(
    account_id: str, asset_id: str, title: str = "", description: str = "", workspace_id: str = ""
) -> dict[str, Any]:
    """Confirmation required: publish an asset to a platform with a logged-in account.

    This posts PUBLICLY under the user's account — it always waits for their approval.
    Get account_id from list_publish_accounts. Do NOT use to export a file locally;
    that is render_sequence.
    """
    confirmation = open_card(
        {
            "workspace_id": workspace_id or default_workspace_id(),
            "tool": "publish_asset",
            "requested_by": REQUESTED_BY.get(),
            "payload": {
                "account_id": account_id,
                "asset_id": asset_id,
                "title": title,
                "description": description,
            },
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="reads")
def list_publish_accounts(workspace_id: str = "") -> list[dict[str, Any]]:
    """Read-only: the platform accounts already logged in, for publish_asset."""

    workspace_id = workspace_id or default_workspace_id()
    return use_case(publish_uc.list_accounts, workspace_id, out=PublishAccountOut)


@tool(effect="reads")
def list_publish_tasks(status: str = "", limit: int = 20, workspace_id: str = "") -> list[dict[str, Any]]:
    """Read-only: recent publish tasks, newest first, with what was published where.

    A successful task carries `post`: {platform, post_id, url, ids, published_at} — the post's
    ID on the platform (Douyin/TikTok aweme_id, Bilibili bvid, Xiaohongshu note_id, YouTube
    video id). Use it to look the post up later (e.g. TikHub stats by that ID). An empty
    post_id means the platform's reply was not read at publish time — do not guess one from
    the title. `status` filters (success / failed / running / pending …).
    """

    workspace_id = workspace_id or default_workspace_id()
    tasks = use_case(publish_uc.list_tasks_with_status, workspace_id, out=PublishTaskOut)
    if status:
        tasks = [task for task in tasks if task.get("status") == status]
    keep = ("id", "platform", "account_name", "asset_id", "asset_name", "title", "status", "error", "post", "created_at")
    return [{key: task.get(key) for key in keep} for task in tasks[: max(1, min(int(limit or 20), 100))]]
