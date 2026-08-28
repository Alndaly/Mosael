"""结构性约束:**适配器读的每个参数键,描述符都得声明。**

描述符的 `parameter_keys` 有两个身份:界面据它决定出哪些控件,校验器据它决定**拦下什么**
(operations.validate_against_capabilities —— 不在名单里的参数当场报错)。
所以适配器读一个没被声明的键时,那个键只有两种下场,没有第三种:

  · 有人真的发它 → **提交被自己的校验器拦下**。ComfyUI 就是这样断的:适配器一直读
    `workflow` / `workflow_params`,界面也一直在发(选一个 ComfyUI 里保存的工作流),
    只是描述符没声明 —— 于是"选了工作流就提交不了",而选工作流正是接 ComfyUI 的理由。
    没有一条测试覆盖"带工作流提交",所以它一直是绿的。
  · 没人发它 → 那段代码**永远不会执行**。Veo 的 `first_frame_base64` / `image_base64` /
    `first_frame_mime_type` 全仓没有任何地方设置,读了个寂寞;万相的
    `parameters.get("duration_seconds") or parameters.get("duration")` 后半段同理。

两种下场都不会报错,而第一种用户看得见、第二种谁都看不见 —— 正是最难查的那类。

## 它抓不到什么

判据是「**这家有没有任何模型认这个键**」,粒度到 vendor 为止。同一个适配器模块常常同时服务
图像和视频(ComfyUI 就是),而 `parameters.get("x")` 这一行属于哪一条路,静态扫描分不出来 ——
所以「图像描述符漏了、视频描述符有」这种 kind 之间的不对称,这条测试看不见。
真实那次 ComfyUI 是两个描述符**都**漏了,所以它拦得住;只漏一半的话得靠别的方式发现。
不写在这儿的话,下一个人会以为这条已经把这一类全包了。

## 这条是棘轮:名单只减不增

`_UNDECLARED` 里是**已知还没对齐的**键,每一条都写清了为什么。想加新的键?
去描述符里声明它 —— 那才是让它真正可用的动作。名单变长意味着又多了一个
"写了但够不着"的能力,所以这里只允许它变短。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import pathlib
import re

from app.domain.generation import catalog as C
from app.domain.generation.operations import allowed_parameter_keys

#: `request.parameters.get("x")` 和 `request.parameters["x"]` 两种写法。
_READS = re.compile(r'(?:request\.)?parameters(?:\.get\(|\[)\s*["\']([a-z_0-9]+)["\']')

#: 语音适配器不走生成校验那条路(它们的入口是配音/克隆,没有 parameter_keys 这个概念)。
_NOT_GENERATION = {"speech"}

#: **已知的缺口。只减不增。** 每一条都是「适配器实现了,但用户够不着」。
_UNDECLARED = {
    # 可灵的真旋钮,描述符里一个都没有 —— 而可灵本身就是唯一没拿真机核过的一家
    # (没有密钥),所以补声明之前得先确认这些键名和取值是对的,照文档补等于把没验证过的
    # 东西又往前推一层。
    ("kling.py", "mode"),
    ("kling.py", "external_task_id"),
    # Veo:这三个键**全仓没有任何地方设置**,读了个寂寞。要么把喂它们的那一半接上,
    # 要么把这几行删掉 —— 同样等有 Google 密钥能验证之后再动。
    ("veo.py", "first_frame_base64"),
    ("veo.py", "first_frame_mime_type"),
    ("veo.py", "image_base64"),
    ("veo.py", "person_generation"),
    # 万相:`duration_seconds or duration` 的后半段。`duration` 没被任何描述符声明,
    # 也就永远到不了 —— 是个够不着的兼容分支。
    ("wan.py", "duration"),
    # 这两个是各自厂商的真旋钮,只是还没接进描述符。
    ("openai.py", "output_format"),
    ("qwen.py", "prompt_extend"),
}


def _allowed_by_vendor() -> dict[str, set[str]]:
    """每家**认哪些参数键** —— 口径来自校验器自己那一份(operations.allowed_parameter_keys),
    不在这里重算。重算就是又抄了一张表,而这条测试正是为抄表而设的。"""
    keys: dict[str, set[str]] = {}
    for model in C.BUILTIN_MODELS:
        keys.setdefault(model["provider"], set()).update(allowed_parameter_keys(model["capabilities"]))
    return keys


def _vendor_by_module() -> dict[str, set[str]]:
    """哪个适配器模块服务哪几家 —— **从注册表反查**,不靠文件名猜。

    一个模块可以服务多家(image/openai 同时是 openai 和 openai-compatible),所以值是一个集合;
    判定时取并集:这个键只要被它服务的任意一家声明了,就算够得着。
    """
    from app.ai.providers import get_provider

    out: dict[str, set[str]] = {}
    for model in C.BUILTIN_MODELS:
        provider = get_provider(model["provider"], model["kind"])
        if provider is not None:
            out.setdefault(type(provider).__module__, set()).add(model["provider"])
    return out


def _allowed_anywhere() -> set[str]:
    """任何一家认的键。只给认不出归属的共用件(base.py)兜底用。"""
    keys: set[str] = set()
    for model in C.BUILTIN_MODELS:
        keys.update(allowed_parameter_keys(model["capabilities"]))
    return keys


def test_适配器读的参数键都被声明过() -> None:
    """**按 vendor 判,不是按全体判。**

    并成一张大表的话,这条测试抓不住真正的形状:ComfyUI 那次是图像描述符漏了 `workflow`
    而视频描述符有 —— 于是"有人声明过"成立,而图像那条路照样被拦下。判据必须是
    「**这家的**描述符声明了吗」。
    """
    by_vendor = _allowed_by_vendor()
    by_module = _vendor_by_module()
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "ai" / "providers"

    gaps: set[tuple[str, str]] = set()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts or path.parent.name in _NOT_GENERATION:
            continue
        module = "app.ai." + ".".join(path.relative_to(root.parents[1]).with_suffix("").parts[1:])
        vendors = by_module.get(module)
        # 认不出归属的(base.py 这种共用件)退回全体口径 —— 它本来就不属于某一家。
        declared = (
            set().union(*(by_vendor.get(v, set()) for v in vendors)) if vendors else _allowed_anywhere()
        )
        for key in set(_READS.findall(path.read_text())):
            if key not in declared:
                gaps.add((path.name, key))

    new = sorted(gaps - _UNDECLARED)
    assert not new, (
        "这些参数键适配器读了、却没有任何描述符声明 —— 发它会被校验器拦下,不发它这段代码就是死的:\n"
        + "\n".join(f"  {where}: {key}" for where, key in new)
        + "\n去 domain/generation/catalog 里声明它们,而不是加进这条测试的豁免名单。"
    )


def test_豁免名单没有过期的条目() -> None:
    """名单里的键如果已经被声明了,就该从名单里划掉 —— 否则它会继续豁免一个已经不存在的问题,
    下次同一个文件真的漏了新键时,读名单的人会以为"这里本来就有豁免"。"""
    by_vendor = _allowed_by_vendor()
    by_module = _vendor_by_module()
    file_to_vendors = {module.rsplit(".", 1)[-1] + ".py": vendors for module, vendors in by_module.items()}
    stale = []
    for where, key in sorted(_UNDECLARED):
        vendors = file_to_vendors.get(where)
        if not vendors:
            continue
        # **按这家判**,不按全体 —— `aspect_ratio` 别家声明了,而 seedance 没有,
        # 按全体判会把它误报成"已经修好了"。
        if key in set().union(*(by_vendor.get(v, set()) for v in vendors)):
            stale.append((where, key))
    assert not stale, f"这些条目已经被描述符声明了,把它们从 _UNDECLARED 里删掉:{stale}"
