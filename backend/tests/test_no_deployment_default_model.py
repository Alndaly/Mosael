"""默认模型只有**我自己**那一档,没有部署兜底。

原本是「自己的 → 部署的 → 没有」。中间那一档删掉了,理由和删掉「随便挑一个可用模型」是同一条:
**替人做的选择必须是他自己做的**。部署默认看起来温和 —— 它只在"你还没设"的时候生效 —— 但它
造成的正是同一种误解:界面上你没选过任何模型,回答却来自某个你不知道的模型,花的是你的额度、
用的是你的钥匙,而你从没同意过。

没设就说没设。这句话用户看得懂,而且他知道下一步做什么(在输入框旁边选一个)。悄悄替他选一个,
他连"发生了什么"都不知道。

顺带删掉的:`for_deployment` 写入口、`/api/admin/provider-defaults` 读入口、管理页那一段界面。
一个不该存在的兜底,连同它的三个入口一起走。
"""

from __future__ import annotations

import pytest

from app.core.db import SessionLocal
from tests.util import add_provider, fresh_client, second_client


def _provider(username: str = "tester") -> str:
    with SessionLocal() as db:
        profile = add_provider(
            db, name="P", vendor="openai-compatible", base_url="http://localhost:1/v1",
            api_key="k", model="m", capability_ids=["chat"], owner_username=username,
            make_default=False,
        )
        db.commit()
        return profile.id


def test_nobody_can_write_a_deployment_default() -> None:
    """连部署管理员也不行 —— 这一档不存在了,不是"权限更高才能设"。"""
    admin = fresh_client()
    profile_id = _provider()

    refused = admin.put(
        "/api/settings/provider-defaults/chat",
        json={"provider_profile_id": profile_id, "model": "m", "for_deployment": True},
    )

    # 多带一个已经没有意义的字段不该让整个请求 422 —— 但它绝不能生效。
    assert refused.status_code in (200, 422), refused.text
    if refused.status_code == 200:
        assert refused.json()["is_mine"] is True, "for_deployment 还在生效"


def test_the_admin_read_endpoint_is_gone() -> None:
    admin = fresh_client()

    assert admin.get("/api/admin/provider-defaults").status_code == 404


def test_someone_elses_default_is_not_mine() -> None:
    """一个人设好了默认,不影响另一个人 —— 后者仍然是"还没选"。"""
    owner = fresh_client()
    profile_id = _provider()
    owner.put(
        "/api/settings/provider-defaults/chat",
        json={"provider_profile_id": profile_id, "model": "m"},
    )

    mate = second_client("mate")
    theirs = mate.get("/api/settings/provider-defaults").json()
    chat = next(row for row in theirs if row["capability"] == "chat")

    assert chat["provider_profile_id"] in (None, ""), "拿到了别人的默认"


def test_resolving_without_my_own_default_gives_nothing() -> None:
    """解析链的终点是 None,不是"某个还凑合的模型"。"""
    from app.domain import provider_models

    fresh_client()
    _provider()

    with SessionLocal() as db:
        user_id = db.execute(
            __import__("sqlalchemy").text("SELECT id FROM users LIMIT 1")
        ).scalar_one()
        assert provider_models.resolve_default(db, "chat", user_id) is None


def test_a_chat_without_a_chosen_model_says_so() -> None:
    """报错要说清下一步做什么,而不是"未配置供应商"。"""
    from app.ai.agent.host import AdapterError, resolve_chat_provider

    fresh_client()
    _provider()

    with SessionLocal() as db:
        user_id = db.execute(
            __import__("sqlalchemy").text("SELECT id FROM users LIMIT 1")
        ).scalar_one()
        with pytest.raises(AdapterError) as caught:
            resolve_chat_provider(db, None, "", user_id=user_id)

    message = str(caught.value)
    assert "选" in message
    assert "部署管理员" not in message, "别再让人去找管理员 —— 那一档没有了"


def test_no_code_path_still_reads_the_empty_owner_row() -> None:
    """形状棘轮:`owner_user_id=""` 那一行不该再被任何地方读或写。

    留一处就等于留着整个兜底 —— 而它的失败方式是静默的:界面显示"还没选",回答却照常来。
    """
    import ast
    import pathlib
    import re

    def prose_lines(source: str) -> set[int]:
        """文档字符串占掉的行号。

        只排除**文档字符串**,不是所有字符串 —— 第一版图省事用 tokenize 把 STRING 全扔了,
        结果把 `"owner_user_id"` 这个键名本身也扔了,于是把兜底原样加回去它照样是绿的。
        一条不会红的棘轮比没有棘轮更坏:它让人以为这里有人守着。
        """
        lines: set[int] = set()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = getattr(node, "body", None)
            if not body or not isinstance(body[0], ast.Expr) or not isinstance(body[0].value, ast.Constant):
                continue
            if isinstance(body[0].value.value, str):
                lines.update(range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))
        return lines

    def cleanup_lines(source: str) -> set[int]:
        """清理这些行的那两个迁移不算违规 —— 禁掉它们等于禁掉清理本身。"""
        # 这两个迁移都必须碰那一列:一个删掉无主的默认行,一个给无主的连接补上主人。
        # 禁掉它们等于禁掉清理本身。按函数名点名放行,而不是放行整个文件。
        # **两个都要收**:上一版 `return` 在第一个匹配就出去了,于是另一个照样被判违规。
        allowed = {
            "_migrate_drop_deployment_defaults",
            "_migrate_connections_get_an_owner",
            "_migrate_plugin_instances_get_an_owner",
        }
        lines: set[int] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.FunctionDef) and node.name in allowed:
                lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
        return lines

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in root.rglob("*.py"):
        source = path.read_text()
        skip = prose_lines(source) | cleanup_lines(source)
        for index, line in enumerate(source.splitlines(), 1):
            if index in skip or line.lstrip().startswith("#"):
                continue
            if re.search(r"""owner_user_id["']?\s*[=:]=?\s*["']\s*["']""", line):
                offenders.append(f"{path.relative_to(root)}:{index}")

    assert not offenders, "部署默认那一行还在被碰:\n  " + "\n  ".join(offenders)


def test_a_deployment_row_left_in_the_database_is_ignored() -> None:
    """就算库里还躺着一行 `owner_user_id=""`(老库、手改、迁移没跑),也不许有人读它。

    这一条比形状棘轮硬:它盯的是**行为**。删掉一档兜底最容易复发的方式,不是有人把代码写回来,
    而是某条解析路径悄悄又多看了一眼那一行 —— 而那时界面仍然显示"还没选",回答却照常来。
    """
    from sqlalchemy import text

    from app.domain import provider_models

    client = fresh_client()
    profile_id = _provider()
    with SessionLocal() as db:
        model_id = db.execute(
            text("SELECT id FROM provider_models WHERE provider_profile_id = :p"), {"p": profile_id}
        ).scalar_one()
        db.execute(
            text(
                "INSERT INTO provider_defaults (capability, owner_user_id, provider_model_id, updated_at) "
                "VALUES ('chat', '', :m, CURRENT_TIMESTAMP)"
            ),
            {"m": model_id},
        )
        db.commit()

    with SessionLocal() as db:
        user_id = db.execute(text("SELECT id FROM users LIMIT 1")).scalar_one()
        assert provider_models.resolve_default(db, "chat", user_id) is None, "又去读那一行了"

    mine = client.get("/api/settings/provider-defaults").json()
    chat = next(row for row in mine if row["capability"] == "chat")
    assert chat["provider_profile_id"] in (None, ""), "界面上冒出了一个我没设过的默认"
