"""把一份**本地素材**变成一条公网可下载的地址 —— 交给声明了这个能力的插件去做。

## 它解决的那个断链

Mosael 是本地优先的:素材在用户自己的盘上,没有公网地址。而有些供应商的某些角色**只收链接**
—— 方舟 Seedance 的参考视频就是一例(参考**图**可以走 Base64,参考**视频**不行,官方文档
明写),视频编辑、视频续写那两条路上的源视频同理。

此前这条路直接断在提交前:界面上拦一句"请改用一条公网直链"。**那是把问题退回给用户** ——
他得自己找个对象存储、自己传、自己签链接、再粘回来,而这四步里每一步都可能做错。

现在多一步:提交时看见这种角色带的是本地素材,就找一个**声明了 `public_url` 能力**的插件
(对象存储三家),让它传上去并交回一条限时直链。用户那一侧只是多等几秒。

## 为什么按声明找,而不是按工具名猜

靠 `*_upload` 这种后缀去猜的话,任何一个叫这个名字的工具都会被当成对象存储 ——
而猜错的表现是**把用户的素材传去了别的地方**。所以插件在清单里显式声明
`"provides": ["public_url"]`,宿主只认这个(见 plugins/manifest.Manifest.provides)。

## 失败要说得出口

三种失败对用户意味着完全不同的下一步,所以分开说:

- **没装**:告诉他装哪几个(而不是"请自行上传到公开地址");
- **装了但没配好**:点名是哪一个实例、缺什么(桶名?密钥?);
- **传失败**:把插件自己的话带出来(桶不存在、密钥没权限、网络不通),并说清素材是哪一份。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: 插件在清单里声明的那个能力名。
PUBLIC_URL = "public_url"
#: 交回来的直链要活多久。一次生成任务在**提交时**就把文件取走,给足余量。
LINK_TTL_SECONDS = 6 * 3600


class NoUploader(RuntimeError):
    """没有可用的上传插件。消息是给用户看的,要说清下一步做什么。"""


def uploaders(db: "Session", workspace_id: str) -> list:
    """能把本地文件变成公网地址的插件实例 —— **按声明找,不按名字猜**。

    按名字排序返回:同一个工作区里配了两家对象存储时,选哪一个必须是稳定的,
    否则同一份素材这次传去 TOS、下次传去 OSS,而用户看不出为什么。
    """
    from app.db.models import PluginInstance
    from app.domain.plugins import instances as inst

    found = []
    for instance in db.query(PluginInstance).all():
        if not instance.enabled:
            continue
        try:
            manifest = inst.manifest_for(db, instance)
        except Exception:  # noqa: BLE001 —— 一个装坏了的插件不该让整条生成链失败
            logger.warning("读不出插件 %s 的清单,跳过", instance.id, exc_info=True)
            continue
        if PUBLIC_URL in manifest.provides:
            found.append((instance, manifest))
    return sorted(found, key=lambda pair: pair[0].name or "")


def _upload_tool(db: "Session", instance) -> str:
    """这个实例里负责上传的那个工具名。"""
    from app.domain.plugins import tools as plugin_tools

    for tool in plugin_tools.all_tools(db, instance):
        name = str(tool.get("name") or "")
        if name.endswith("_upload"):
            return name
    raise NoUploader(f"「{instance.name}」声明了能换公网地址,却没有上传工具 —— 这是插件自己的 bug")


def public_url_for(db: "Session", *, workspace_id: str, asset_id: str, asset_name: str) -> tuple[str, str]:
    """把这份素材传上去,返回 `(直链, 用了哪个插件实例的名字)`。

    找不到可用的插件时抛 `NoUploader`,消息直接给用户看。
    """
    from app.domain.plugins import tools as plugin_tools
    from app.domain.plugins.errors import PluginDomainError

    candidates = uploaders(db, workspace_id)
    if not candidates:
        raise NoUploader(
            f"「{asset_name}」是本地素材,而这个模型的这一项只收公网链接。"
            "装一个对象存储插件(火山引擎 TOS / 阿里云 OSS / Amazon S3)之后它会自动传上去 ——"
            "在「插件」页里装并填上桶和密钥;或者直接粘一条你已有的公网直链。"
        )
    instance, _manifest = candidates[0]

    from app.domain.plugins import instances as inst

    missing = inst.missing_config(db, instance)
    if missing:
        raise NoUploader(
            f"「{instance.name}」还没配好({'、'.join(missing)}),所以「{asset_name}」传不上去。"
            "去插件页把它补齐,或者直接粘一条公网直链。"
        )

    try:
        invocation = plugin_tools.invoke(
            db, instance.id, _upload_tool(db, instance),
            {"asset_id": asset_id, "expires": LINK_TTL_SECONDS},
            workspace_id=workspace_id,
        )
    except PluginDomainError as exc:
        raise NoUploader(f"用「{instance.name}」上传「{asset_name}」失败:{exc}") from exc

    output = invocation.output or {}
    if invocation.status != "succeeded":
        detail = str(output.get("error") or invocation.error or "插件没说原因")
        raise NoUploader(f"用「{instance.name}」上传「{asset_name}」失败:{detail}")
    url = str(output.get("url") or output.get("public_url") or "").strip()
    if not url:
        raise NoUploader(f"「{instance.name}」传完了却没给出地址 —— 这是插件自己的 bug")
    return url, instance.name
