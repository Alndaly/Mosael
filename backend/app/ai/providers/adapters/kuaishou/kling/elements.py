from __future__ import annotations

import hashlib
import time
from typing import Any

from app.ai.providers.contracts.generation import GenerationAdapterError

"""可灵的「主体库」—— 它的多图参考走这条路,不是把几张图挂在生成请求上。

## 为什么要有这个模块

别家的多图参考是**一次性的**:请求里挂几张图,这次生成用一下就完了(火山九张、万相五张)。
可灵不是 —— 它要你先用 2～4 张图**建一个主体**(有名字、有描述,进你的主体库),拿到
`element_id`,生成时再引用它,并在提示词里用 `@名字` 点名。一个主体可以在很多条片子里复用,
一次生成最多引用 3 个。

所以「多图参考」在可灵这边是一次**建档 + 引用**,而不是一次上传。把它硬塞进「挂几张图」
的模型里,要么丢掉复用(每次重建,白花钱),要么丢掉多图(只发第一张)。

## 复用靠名字,不靠我们自己记一张表

主体名字**由那几张图算出来**(内容哈希的前几位)。生成前先查一遍主体库:同一组图已经建过
就直接用,没建过才建。这样不必再开一张表存映射 —— 那张表会和可灵那边的真实状态漂移
(用户在可灵网站上删了主体,我们这边还记着一个死 id)。名字是可灵自己存的,查得到就是真的还在。

文档:创建 `POST /v1/general/advanced-custom-elements`(异步,轮询同一路径 + /{task_id}),
自定义主体列表 `GET /v1/general/advanced-custom-elements`,删除
`POST /v1/general/delete-advanced-elements`。
"""

CREATE_PATH = "/v1/general/advanced-custom-elements"
DELETE_PATH = "/v1/general/delete-advanced-elements"

#: 多图主体要 **1 张正面图 + 1～3 张其他角度**,也就是一共 2～4 张(文档原话:「至少包括 1 张
#: 正面参考图……需包括 1～3 张其他参考图,需与正面参考图有差异」)。
MIN_REFERENCE_IMAGES = 2
MAX_REFERENCE_IMAGES = 4

#: 一次生成最多引用几个主体(文档原话:「最多支持指定 3 个主体」)。
MAX_ELEMENTS_PER_TASK = 3

#: 名字上限 20 字符、描述上限 100 字符 —— 超了是 400,而那时图已经传上去了。
_NAME_LIMIT = 20
_DESCRIPTION_LIMIT = 100

#: 我们建的主体统一带这个前缀,方便用户在可灵的主体库里认出哪些是 Mosael 建的。
NAME_PREFIX = "os-"

_TERMINAL_OK = ("succeed",)
_TERMINAL_BAD = ("failed", "fail", "canceled", "cancelled")


def element_name_for(images: list[str]) -> str:
    """同一组图 → 同一个名字。**顺序也算数** —— 第一张是正面图,换个顺序就是另一个主体。"""
    digest = hashlib.sha256("\n".join(images).encode("utf-8")).hexdigest()
    return f"{NAME_PREFIX}{digest[: _NAME_LIMIT - len(NAME_PREFIX)]}"


def build_create_payload(images: list[str], *, description: str = "") -> dict[str, Any]:
    """把一组参考图翻成建主体的请求体。

    第一张当正面图,其余当其他角度 —— 这是文档要求的形状(`frontal_image` + `refer_images`),
    而不是一个平铺的数组。界面上那几个槽位本来就是有顺序的,第一个就是第一个。
    """
    if not MIN_REFERENCE_IMAGES <= len(images) <= MAX_REFERENCE_IMAGES:
        raise GenerationAdapterError(
            f"可灵的多图参考要 {MIN_REFERENCE_IMAGES}～{MAX_REFERENCE_IMAGES} 张图"
            f"(第一张是正面图,其余是其他角度),这次给了 {len(images)} 张"
        )
    frontal, *others = images
    return {
        "element_name": element_name_for(images),
        # 描述是必填的。用户没写就拿提示词凑一句 —— 空字符串会被拒。
        "element_description": (description or "Mosael 多图参考主体")[:_DESCRIPTION_LIMIT],
        "reference_type": "image_refer",
        "element_image_list": {
            "frontal_image": frontal,
            "refer_images": [{"image_url": one} for one in others],
        },
    }


def extract_element_id(task_payload: dict[str, Any]) -> str | None:
    """建主体是异步的:没好返回 None(继续轮询),失败直接抛。

    形状和生成任务那边一样(code/data/task_status),但**终态词不同** —— 这边是 `succeed`
    而不是 `succeeded`。照抄生成那边的判断会永远轮询到超时。
    """
    code = task_payload.get("code")
    if code not in (None, 0):
        raise GenerationAdapterError(f"可灵建主体失败:{task_payload.get('message') or code}")
    data = task_payload.get("data") if isinstance(task_payload.get("data"), dict) else task_payload
    status = str(data.get("task_status") or "").lower()
    if status in _TERMINAL_BAD:
        raise GenerationAdapterError(f"可灵建主体失败:{data.get('task_status_msg') or status}")
    if status not in _TERMINAL_OK:
        return None
    for element in (data.get("task_result") or {}).get("elements") or []:
        if element.get("element_id") not in (None, ""):
            return str(element["element_id"])
    raise GenerationAdapterError("可灵建主体成功却没有返回 element_id")


def find_element_id(listing: dict[str, Any], name: str) -> str | None:
    """在主体库列表里找同名的那个。

    只认 `status == succeed` 的:被删掉的主体照样留在列表里(状态是 `deleted`),拿它的 id
    去生成会被拒,而错误信息说的是"主体不存在" —— 用户完全不知道那是我们自己翻出来的旧记录。
    """
    for task in listing.get("data") or []:
        for element in ((task.get("task_result") or {}).get("elements")) or []:
            if element.get("element_name") == name and str(element.get("status") or "") == "succeed":
                return str(element.get("element_id"))
    return None


def ensure_element(
    client: Any,
    images: list[str],
    *,
    description: str = "",
    poll_interval: float = 3.0,
    poll_timeout: float = 300.0,
) -> str:
    """拿到这组图对应的主体 id:**先查有没有,没有才建**。

    不查直接建的话,每生成一条片子就多一个同样的主体 —— 建主体是要扣积分的,而且用户的
    主体库很快会被同一个人塞满几十份。
    """
    payload = build_create_payload(images, description=description)
    name = payload["element_name"]

    existing = client.get(CREATE_PATH, params={"pageNum": 1, "pageSize": 500})
    if existing.status_code == 200:
        found = find_element_id(existing.json(), name)
        if found:
            return found

    created = client.post(CREATE_PATH, json=payload)
    created.raise_for_status()
    task_id = ((created.json().get("data") or {}).get("task_id")) or ""
    if not task_id:
        raise GenerationAdapterError("可灵建主体没有返回任务 id")

    deadline = time.time() + poll_timeout
    while time.time() < deadline:
        polled = client.get(f"{CREATE_PATH}/{task_id}")
        polled.raise_for_status()
        element_id = extract_element_id(polled.json())
        if element_id:
            return element_id
        time.sleep(poll_interval)
    raise GenerationAdapterError("可灵建主体超时")


def build_element_contents(element_ids: list[str]) -> list[dict[str, Any]]:
    """把主体 id 翻成生成请求 contents 数组里的条目。

    `id` 是**任务内的索引名**,提示词里用 `@名字` 点它;文档要求同一任务里不能重复。
    """
    if len(element_ids) > MAX_ELEMENTS_PER_TASK:
        raise GenerationAdapterError(f"可灵一次最多引用 {MAX_ELEMENTS_PER_TASK} 个主体,这次给了 {len(element_ids)} 个")
    return [
        {"type": "element", "element_id": str(one), "id": f"element_{index + 1}"}
        for index, one in enumerate(element_ids)
    ]


__all__ = [
    "CREATE_PATH",
    "DELETE_PATH",
    "MIN_REFERENCE_IMAGES",
    "MAX_REFERENCE_IMAGES",
    "MAX_ELEMENTS_PER_TASK",
    "build_create_payload",
    "build_element_contents",
    "element_name_for",
    "ensure_element",
    "extract_element_id",
    "find_element_id",
]
