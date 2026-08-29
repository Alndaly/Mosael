"""结构性约束:**「有哪几种输入素材角色」只有一个产地。**

产地是 `ai/providers/base.SOURCE_ROLES`(名字)和 `domain/generation/catalog.SOURCE_ROLE_LABELS`
(中文名)。catalog 里那张表的注释已经把这件事的历史写清楚了 —— 它曾经存在三份,而
「新增角色时漏掉哪一份都不会报错,只是智能体不知道有这个东西,于是永远不会用它」。

到这次为止还活着的抄件有两份,都不会报错、只会安静地少一块:

  · **工作流「AI 生成素材」节点**的 source_assets 说明,是手写的一串角色名。今天八种恰好
    写全了,而加第九种时没有任何东西提醒你回来补 —— 后果是工作流编辑器和智能体都不知道
    有这种角色,于是那条路上它等于不存在。
  · **接口 schema** 的 role 字段,是一条手写的正则。这一份更糟:描述符说支持,接口却会以
    「正则不匹配」拒掉它 —— 报的话和"角色"两个字没有关系,查起来要绕一大圈。

两份现在都改成从产地生成。这条测试钉住它们**保持**生成,而不是哪天又被人展开成字面量。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

from app.ai.providers.base import SOURCE_ROLES
from app.domain.generation.catalog import SOURCE_ROLE_LABELS


def test_两张产地表本身对得上() -> None:
    """名字表和中文名表必须一一对应 —— 少一条就是「有这个角色但界面上没名字」。"""
    assert set(SOURCE_ROLE_LABELS) == set(SOURCE_ROLES), (
        f"名字表与中文名表对不上:只在名字表={set(SOURCE_ROLES) - set(SOURCE_ROLE_LABELS)}、"
        f"只在中文名表={set(SOURCE_ROLE_LABELS) - set(SOURCE_ROLES)}"
    )


def test_工作流节点的说明覆盖全部角色() -> None:
    """**两种语言都要覆盖。** 这句话是现算的,而它有中英两份模板 —— 只有中文那句跟着角色表
    走的话,加第九种角色时英文界面和读英文的智能体永远不知道有这个东西。

    打接口而不是读目录:目录里现在存的是 key + 参数,句子在出口才组装。
    """
    from tests.util import fresh_client

    client = fresh_client()
    for header in ("zh-CN", "en-US"):
        types = client.get("/api/workflows/node-types", headers={"Accept-Language": header}).json()
        text = next(one for one in types if one["type"] == "ai_generate")["config"]["source_assets"]["description"]
        missing = [role for role in SOURCE_ROLES if role not in text]
        assert not missing, f"{header} 下这些角色没被说明:{missing}"


def test_接口_schema_收全部角色() -> None:
    from app.api.schemas import SourceAssetRef

    for role in SOURCE_ROLES:
        assert SourceAssetRef(asset_id="x", role=role).role == role, f"接口拒收 {role}"


def test_接口_schema_仍然拦得住乱写的角色() -> None:
    """放开成"什么都收"也能让上面那条绿 —— 那等于把校验挪到更晚的地方,报错更难懂。"""
    import pytest
    from pydantic import ValidationError

    from app.api.schemas import SourceAssetRef

    with pytest.raises(ValidationError):
        SourceAssetRef(asset_id="x", role="definitely_not_a_role")


def test_节点说明是算出来的_不是写死的() -> None:
    """**这条才是重点。** 上面几条只证明"今天是齐的",而齐可以是手抄碰巧抄全了。

    判据是「节点里那段说明 == 生成函数现在算出来的」。写死一段和今天一字不差的字面量今天也能过,
    但加一种角色之后两者就不再相等 —— 和下面那条正则用的是同一个办法。

    不用 importlib.reload:重载 `app.domain.workflows` 会换掉 WorkflowDomainError 这个类对象,
    而别处 `except` 住的是旧的那个 —— 于是后面的用例莫名其妙地红,而原因在这条测试里。
    (第一版就是这么干的,连累了 test_workflows 两条。)
    """
    from app.domain.workflows import NODE_TYPES, _generation_parameters_help, _source_assets_help

    config = NODE_TYPES["ai_generate"]["config"]
    # **比对的是接线,不是函数。** 只调一次生成函数、看它算得对不对是没用的:
    # 节点里塞一段写死的字面量,那个函数照样算得好好的,而节点用的根本不是它。
    # (第一版就是这么写的,两种写死的破坏它一个都没抓到。)
    assert config["source_assets"]["description_params"] == _source_assets_help(), (
        "节点的素材说明不是生成的那一份 —— 加一种角色时它不会跟着变"
    )
    assert config["parameters"]["description_params"] == _generation_parameters_help(), (
        "节点的参数说明不是生成的那一份 —— 描述符里加一个参数时它不会跟着变"
    )


def test_接口的角色正则是从产地拼的() -> None:
    """正则在类定义时就烤进去了,没法靠改表验证,所以直接比对**它是否等于产地拼出来的那一条**。

    手写的和生成的今天可能一字不差 —— 但加一种角色之后就不再相等,这条会红。
    """
    from app.api.schemas import SourceAssetRef

    patterns = [m.pattern for m in SourceAssetRef.model_fields["role"].metadata if hasattr(m, "pattern")]
    assert patterns, "role 字段没有取值约束了 —— 那等于把校验挪到更晚、报错更难懂的地方"
    assert patterns[0] == f"^({'|'.join(SOURCE_ROLES)})$", (
        f"role 的正则不是从 SOURCE_ROLES 拼出来的:{patterns[0]}"
    )


def test_没有第二处把角色名铺开写() -> None:
    """等值比对有个盲区:**今天**手写的和生成的可能一字不差,那时它分不出来。

    (实测过:把 role 的正则展开成字面量,等值那条照样绿 —— 因为两者此刻相同。)

    所以再加一道扫描,和 test_chat_single_implementation 用的是同一个办法。判据取**字符串
    常量**(走 AST,所以注释和普通代码不算):一个字面量里塞了三个以上角色名,或者一个文件里
    有三个以上"整个就是一个角色名"的字面量 —— 两种都是把那张表又抄了一遍。

    第一版只找带引号的 `"first_frame"`,漏掉了正则那种**一整串里的子串**(`a|b|c`),
    于是把正则展开成字面量它抓不到。
    """
    import ast
    import pathlib as _p

    app_dir = _p.Path(__file__).resolve().parents[1] / "app"
    #: 产地本身,以及供应商各自的**线上字段名映射**(万相把 source_video 叫 video,
    #: 那是两套命名之间的翻译,不是抄我们的表)。
    allowed = ("providers/base.py", "generation/catalog.py", "video/wan.py")

    offenders = []
    for path in sorted(app_dir.rglob("*.py")):
        if "__pycache__" in path.parts or any(str(path).endswith(one) for one in allowed):
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # 不是这条测试该管的事
            continue
        literals = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        exact = {text for text in literals if text in SOURCE_ROLES}
        crowded = next((text for text in literals if sum(role in text for role in SOURCE_ROLES) >= 3), None)
        if crowded is not None:
            offenders.append((str(path.relative_to(app_dir)), f"一个字面量里塞了多种角色:{crowded[:90]}"))
        elif len(exact) >= 3:
            offenders.append((str(path.relative_to(app_dir)), f"逐个铺开:{sorted(exact)}"))
    assert not offenders, (
        "这些地方把角色名铺开写了 —— 又是一份会漂的抄件,该从 SOURCE_ROLES 生成:\n"
        + "\n".join(f"  {where}: {why}" for where, why in offenders)
    )
