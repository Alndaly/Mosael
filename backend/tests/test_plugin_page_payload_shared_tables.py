"""插件页那一份工具清单:重复的大表只搬一次,而且**界面读的那一份一个字节都不动**。

## 现场

`673bd0b7d` 修的是插件 → 宿主那一跳(工具清单撞 1MB 的线)。那一跳之后的形状是**展平**的:同一张 LoRA 表
在一条工具的 `input_schema` 里又各占一格。对着真机 8120 量,`GET /api/plugins` 2,929,540 字节,其中
`input_schema` 832,308 —— 里面 555,529 是重复的同一批表(一个工具里同一张 LoRA 表贴 4 份,46 个工具里
同一张贴 25 份)。后端的处理只要 63ms:这是**载荷**膨胀,不是慢查询。

界面读的不是它:`PluginsTable`/`ToolRow` 画试跑表单读的是 `form`。所以 `input_schema` 里重复的表可以照
插件那一套收一次(`shared_tables` + `x-shared-table`,键用**内容指纹**)—— 五个字段名不同、内容逐字节相同
(`lora_name_105` … `lora_name_109`)本来就该只搬一次。`form` 里那份相同的表**不能**这么收:界面按
`options` 直接画下拉,格子上换成引用它就画不出来(那是 UI 侧接缝,ADR 0045 §5「文件清单按需取」)。

## 钉的是什么

- **展平之后逐字节相同**(连键的顺序:引用占的是 `enum` 原来的位置)—— 这条是硬的,写成断言;
- 去重是**有因果的**:同一个连接、同一份库里的清单,把 `share` 关掉再取一次,那一份就是去重前的形状:
  展平等价性照旧、体积断言必须红。所以这条测试自己带着「关掉」的那一半;
- `form` 两次逐字节相同:界面那一侧零改动;
- 上限(`MAX_TABLE_BYTES`):一张自己就超过 256KB 的表不进共享表,照旧逐格写全 —— 不截断、不丢选项。
"""

from __future__ import annotations

import json

import pytest

from app.domain.plugins import shared_tables
from tests import comfyui_big_catalog
from tests.fake_comfyui import FakeComfyUI, comfyui_grants
from tests.util import fresh_client

PACKAGE = "dev.mosael.comfyui"
#: 维护者那台上开着的工具数(截图里那句「已开启 42 / 42 个工具」)。
MAINTAINER_TOOLS = 42
PLAIN_WORKFLOWS = MAINTAINER_TOOLS - 3


def _compact(node: object) -> str:
    """一条响应里那一格的字节形态 —— 逐字节比的就是它(键的顺序也算)。"""
    return json.dumps(node, ensure_ascii=False, separators=(",", ":"))


def _bytes(node: object) -> int:
    return len(_compact(node).encode("utf-8"))


@pytest.fixture
def comfy():
    with FakeComfyUI() as server:
        comfyui_big_catalog.install(server.state, plain_workflows=PLAIN_WORKFLOWS)
        yield server


@pytest.fixture
def catalog(comfy):
    """接上这台假 ComfyUI、刷新一次,然后取两份:`shared` 是这一版,`inline` 是把去重关掉的那一份。"""
    client = fresh_client()
    created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
    assert created.status_code == 200, created.text
    instance_id = created.json()["id"]
    client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": comfyui_grants()})
    assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
    refreshed = client.post(f"/api/plugins/instances/{instance_id}/refresh")
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["capability_status"]["tools"]["tools"] == MAINTAINER_TOOLS

    shared = client.get("/api/plugins")
    assert shared.status_code == 200
    return client, shared.content


def _tools(payload: bytes) -> dict[str, dict]:
    """这一份响应里 ComfyUI 那个实例的工具,按名字。"""
    for package in json.loads(payload):
        if package["id"] != PACKAGE:
            continue
        for instance in package["instances"]:
            return {tool["name"]: tool for tool in instance["tools"]}
    raise AssertionError("响应里没有 ComfyUI 实例")


def test_插件页那一份_重复的大表只搬一次_展平后逐字节相同(catalog, monkeypatch) -> None:
    """这一版交出去的那一份,和「去重关掉」那一份比:展平后逐字节相同,而它更小。"""
    client, shared_payload = catalog
    tools = _tools(shared_payload)
    assert len([name for name in tools if name.startswith("wf_")]) == MAINTAINER_TOOLS, \
        "假 ComfyUI 要报到维护者那个数,不然这条什么都没量"

    # 把去重关掉:同一个库、同一条连接,只是宿主不再收那一份 —— 这就是去重前的形状。
    monkeypatch.setattr(shared_tables, "share", lambda output: output)
    inline_payload = client.get("/api/plugins").content
    inline = _tools(inline_payload)

    # **体积**:去重那一份更小。这一条就是「把去重关掉必须红」的那一条 —— 上面那次取的就是关掉的那一份。
    assert len(shared_payload) < len(inline_payload) * 0.98, \
        f"共享之后没小多少:{len(shared_payload)} / {len(inline_payload)}"
    refs = sum(_compact(tool["input_schema"]).count(shared_tables.REF_KEY) for tool in tools.values())
    assert refs, "一处引用都没有:这一版没在共享,这条量的是假的"

    for name, tool in tools.items():
        # **最硬的一条**:展平回来和去重前逐字节相同(键的顺序也一样)。
        expanded = shared_tables.expand(tool["input_schema"])
        assert _compact(expanded) == _compact(inline[name]["input_schema"]), f"{name} 展平后和去重前不一样"
        # 界面读的那一份两次逐字节相同:去重一个像素都不该动它。
        assert _compact(tool["form"]) == _compact(inline[name]["form"]), f"{name} 的 form 变了"
    # 每一格下拉都还在(不是少发了几张表):展平之后两边的值总数一样。
    def _values(one: dict[str, dict]) -> int:
        return sum(len(prop.get("enum") or []) for tool in one.values()
                   for prop in ((shared_tables.expand(tool["input_schema"]).get("properties") or {}).values())
                   if isinstance(prop, dict))

    assert _values(tools) == _values(inline), "展平之后少了几格下拉"


def test_界面读的那一份里没有恒等的显示名(catalog) -> None:
    """`form.option_labels` 里 `{值: 值}` 那种项不写 —— 界面读的是 `option_labels?.[值] ?? 值`。

    这一格曾经是整份载荷里最大的一块(真机 1,216,752 字节,98.4% 的项 label 就是 value)。值本身照样
    整张在 `options` 里;少的是那一份**照抄自己**的显示名表。
    """
    from app.domain.workflows.node_catalog import option_label

    _client, payload = catalog
    tools = _tools(payload)

    labels_total = options_total = 0
    for name, tool in tools.items():
        for key, spec in tool["form"].items():
            if not isinstance(spec, dict) or not isinstance(spec.get("options"), list):
                continue
            labels = spec.get("option_labels") or {}
            labels_total += _bytes(labels)
            options_total += _bytes(spec["options"])
            # 值一个都不少(照旧是整张下拉,ADR 0044 修订):声明里那一格有的,这里一项不少。
            enum = ((tool["input_schema"].get("properties") or {}).get(key) or {}).get("enum")
            if enum is not None:
                assert len(spec["options"]) == len(enum), f"{name}.{key} 的下拉比声明里那张短了"
            for option in spec["options"]:
                # 界面上那一行字:去重前是 `option_labels?.[值] ?? 值`,现在还是同一句 —— 逐项相同。
                assert (labels.get(option) or option) == option_label(key, str(option), "zh")
                # 恒等项一个都不留。
                assert labels.get(option) != option, f"{name}.{key} 还留着恒等显示名"

    assert options_total > 100_000, "假 ComfyUI 的下拉太小,这条量不到什么"
    assert labels_total < options_total * 0.1, f"显示名表还是太大:{labels_total} / {options_total}"


def test_共享表的上限_太大的表不进共享_照旧逐格写全() -> None:
    """一张自己就超过上限的表是**一份文件清单**,不是下拉:不截断、不丢选项,只是不共享它。"""
    #: 比上限还大的一张表:值逐字节相同、重复三次 —— 没有上限的话它会被共享。
    big = [f"{index:06d}-{'x' * 40}.safetensors" for index in range(8000)]
    assert _bytes(big) > shared_tables.MAX_TABLE_BYTES
    schema = {"properties": {f"lora_name_{index}": {"type": "string", "enum": big} for index in range(3)}}
    assert shared_tables.share(schema) == schema, "超过上限的表被共享了"
    assert shared_tables.TABLE_KEY not in shared_tables.share(schema)

    #: 上限之内的照旧共享,而且展平回来逐字节相同。
    small = ["a.safetensors", "b.safetensors"] + ["c" * 40 + ".safetensors"] * 40
    other = {"properties": {f"lora_name_{index}": {"type": "string", "enum": small} for index in range(3)}}
    shared = shared_tables.share(other)
    assert shared_tables.TABLE_KEY in shared
    assert len(_compact(shared)) < len(_compact(other))
    assert shared_tables.expand(shared) == other
    assert _compact(shared_tables.expand(shared)) == _compact(other)


def test_共享不改传进来的那一份() -> None:
    """库里那份 `discovered_tools` 是调用方的东西,`share` 只交回新的一棵,不就地改它。"""
    values = ["a.safetensors", "b.safetensors"] + ["c" * 40 + ".safetensors"] * 40
    schema = {"properties": {"lora_1": {"type": "string", "enum": list(values)},
                             "lora_2": {"type": "string", "enum": list(values)}}}
    frozen = json.dumps(schema, ensure_ascii=False)
    shared = shared_tables.share(schema)
    assert shared_tables.TABLE_KEY in shared
    assert json.dumps(schema, ensure_ascii=False) == frozen, "传进来的那一份被改了"


def test_引用占的是_enum_原来的位置() -> None:
    """展平回来连键的顺序都一样 —— 引用写在 `enum` 那一格上,不是追在最后。"""
    values = ["a.safetensors", "b.safetensors"] + ["c" * 40 + ".safetensors"] * 40
    spec = {"type": "string", "enum": values, "title": "LoRA"}
    schema = {"properties": {"lora_1": dict(spec), "lora_2": dict(spec)}}
    frozen = _compact(schema)
    shared = shared_tables.share(schema)
    prop = shared["properties"]["lora_1"]
    assert list(prop) == ["type", shared_tables.REF_KEY, "title"]
    assert _compact(shared_tables.expand(shared)) == frozen


def test_没共享过的那一份原样交回() -> None:
    """没有重复表的 schema 一个字节都不动(同一个对象,不做深拷贝)。"""
    schema = {"properties": {"steps": {"type": "integer", "default": 20}}}
    assert shared_tables.share(schema) is schema
    assert shared_tables.expand(schema) is schema
    assert shared_tables.expand({"properties": {}, shared_tables.TABLE_KEY: {}}) == {"properties": {}}
