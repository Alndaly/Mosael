"""把一份**本地素材**变成一条公网可下载的地址 —— 交给声明了这个能力的插件去做。

## 它解决的那个断链

Mosael 是本地优先的:素材在用户自己的盘上,没有公网地址。而有些供应商的某些角色**只收链接**
—— 方舟 Seedance 的参考视频就是一例(参考**图**可以走 Base64,参考**视频**不行,官方文档
明写),视频编辑、视频续写那两条路上的源视频同理。

此前这条路直接断在提交前:界面上拦一句"请改用一条公网直链"。**那是把问题退回给用户** ——
他得自己找个对象存储、自己传、自己签链接、再粘回来,而这四步里每一步都可能做错。

现在多一步:提交时看见这种角色带的是本地素材,就找一个**声明了 `public_url` 能力**的插件
(对象存储四家),让它传上去并交回一条限时直链。用户那一侧只是多等几秒。

## 为什么按声明找,而不是按工具名猜

靠 `*_upload` 这种后缀去猜的话,任何一个叫这个名字的工具都会被当成对象存储 ——
而猜错的表现是**把用户的素材传去了别的地方**。所以插件在清单里显式声明
`"provides": ["public_url"]`,宿主只认这个(见 plugins/manifest.Manifest.provides)。

## 用哪一家

- **只看发起人自己的实例。** 存储实例是个人的(桶和密钥都是他的);此前查的是整个部署里的全部
  实例,多人部署时 A 的素材会用 B 的桶和密钥传上去 —— 文件落在别人的桶里,钱也记在别人头上。
- **只看配好的。** 桶名、密钥缺一项的不算候选。
- **配好了一家就用它;配好了几家,用他定为默认的那家**(「设置 → 视频生成」的「素材外链」,
  存在 PluginCapabilityDefault)。**没定就当场问,不替他挑** —— 此前按实例名的字母序取第一个,
  谁被用上取决于它叫什么。
- 上传工具由工具自己声明(清单里工具上的 `provides`),不按 `_upload` 后缀猜。

## 同一份素材不重复传

链接按(素材, 存储实例)记住(PluginPublicLink),还在有效期里就直接用。此前同一份参考视频
点两次生成就传两次。

## 失败要说得出口

每一种失败对用户意味着不同的下一步,所以分开说:

- **没装 / 没有自己的**:告诉他装哪几个(而不是"请自行上传到公开地址");
- **装了但没配好**:点名是哪一个实例、缺什么(桶名?密钥?);
- **配好了几家却没定默认**:点名是哪几家,说去哪儿定;
- **插件版本太旧**(包上声明了能力、却没有工具认领):去插件页更新;
- **传失败**:把插件自己的话带出来(桶不存在、密钥没权限、网络不通),并说清素材是哪一份。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: 插件在清单里声明的那个能力名。
PUBLIC_URL = "public_url"
#: 交回来的直链要活多久。一次生成任务在**提交时**就把文件取走,给足余量。
LINK_TTL_SECONDS = 6 * 3600
#: 复用一条缓存的直链时,至少还要剩这么久 —— 供应商排队到真正取文件,中间可能隔一阵。
REUSE_MARGIN = timedelta(hours=1)


class NoUploader(RuntimeError):
    """没有可用的上传插件。消息是给用户看的,要说清下一步做什么。"""


def _missing(db: "Session", instance) -> list[str]:
    """这个实例还缺哪些必填项(配置和凭据都算)。"""
    from app.domain.plugins import instances as inst

    manifest = inst.manifest_for(db, instance)
    values = inst.credential_values(db, instance.id)
    return inst.missing_config(db, instance) + [
        spec.label for spec in manifest.credentials if spec.required and not values.get(spec.key)
    ]


def uploaders(db: "Session", owner_user_id: str | None) -> list:
    """这个人**自己的**、启用着的、声明了 `public_url` 的插件实例 —— 按声明找,不按名字猜。"""
    from sqlalchemy import select

    from app.db.models import PluginInstance
    from app.domain.plugins import instances as inst

    if not owner_user_id:
        return []
    found = []
    rows = db.scalars(select(PluginInstance).where(
        PluginInstance.owner_user_id == owner_user_id, PluginInstance.enabled.is_(True),
    ))
    for instance in rows:
        try:
            manifest = inst.manifest_for(db, instance)
        except Exception:  # noqa: BLE001 —— 一个装坏了的插件不该让整条生成链失败
            logger.warning("读不出插件 %s 的清单,跳过", instance.id, exc_info=True)
            continue
        if PUBLIC_URL in manifest.provides:
            found.append((instance, manifest))
    return sorted(found, key=lambda pair: pair[0].name or "")


def default_uploader_id(db: "Session", owner_user_id: str) -> str | None:
    from app.domain.plugins import capability_defaults

    return capability_defaults.default_of(db, owner_user_id, PUBLIC_URL)


def storage_choices(db: "Session", owner_user_id: str) -> dict:
    """设置页「素材外链」那一格要画的东西:我的每一家存储(配没配好、缺什么)、我定的那家,
    以及没定时实际会用哪一家(只有一家配好时)。"""
    candidates = uploaders(db, owner_user_id)
    options = [
        {"instance_id": instance.id, "name": instance.name, "missing": _missing(db, instance)}
        for instance, _manifest in candidates
    ]
    ready = [option for option in options if not option["missing"]]
    chosen = default_uploader_id(db, owner_user_id)
    if chosen not in {option["instance_id"] for option in options}:
        chosen = None
    return {
        "current": chosen,
        "automatic": ready[0]["instance_id"] if chosen is None and len(ready) == 1 else None,
        "options": options,
    }


def choose_uploader(db: "Session", owner_user_id: str | None, asset_name: str):
    """挑出这一次用哪一家存储,挑不出来时抛 `NoUploader`(消息给用户看)。"""
    candidates = uploaders(db, owner_user_id)
    if not candidates:
        raise NoUploader(
            f"「{asset_name}」是本地素材,而这个模型的这一项只收公网链接。"
            "装一个对象存储插件(火山引擎 TOS / 阿里云 OSS / 腾讯云 COS / Amazon S3)之后它会自动传上去 ——"
            "在「插件」页里装并填上桶和密钥;或者直接粘一条你已有的公网直链。"
        )
    chosen_id = default_uploader_id(db, owner_user_id or "")
    chosen = next((pair for pair in candidates if pair[0].id == chosen_id), None)
    if chosen is None:
        ready = [pair for pair in candidates if not _missing(db, pair[0])]
        if len(ready) == 1:
            chosen = ready[0]
        elif not ready:
            first = candidates[0][0]
            raise NoUploader(
                f"「{first.name}」还没配好({'、'.join(_missing(db, first))}),所以「{asset_name}」传不上去。"
                "去插件页把它补齐,或者直接粘一条公网直链。"
            )
        else:
            names = "、".join(f"「{pair[0].name}」" for pair in ready)
            raise NoUploader(
                f"你配好了几家对象存储({names}),「{asset_name}」要传去哪一家还没定。"
                "去「设置 → 视频生成」的「素材外链」里选一家,再生成一次。"
            )
    instance, manifest = chosen
    missing = _missing(db, instance)
    if missing:
        raise NoUploader(
            f"「{instance.name}」还没配好({'、'.join(missing)}),所以「{asset_name}」传不上去。"
            "去插件页把它补齐,或者直接粘一条公网直链。"
        )
    tool = manifest.tool_providing(PUBLIC_URL)
    if not tool:
        raise NoUploader(f"「{instance.name}」的插件版本太旧 —— 去「插件」页的市场里把它更新到最新,再生成一次。")
    return instance, tool


def public_url_for(
    db: "Session", *, owner_user_id: str | None, workspace_id: str, asset_id: str, asset_name: str,
) -> tuple[str, str]:
    """把这份素材传上去(或复用还没过期的那条),返回 `(直链, 用了哪个插件实例的名字)`。"""
    from app.db.models import PluginPublicLink, now
    from app.domain.plugins import tools as plugin_tools
    from app.domain.plugins.errors import PluginDomainError

    instance, tool = choose_uploader(db, owner_user_id, asset_name)

    cached = db.get(PluginPublicLink, (asset_id, instance.id))
    if cached is not None and cached.expires_at - now() > REUSE_MARGIN:
        return cached.url, instance.name

    try:
        invocation = plugin_tools.invoke(
            db, instance.id, tool, {"asset_id": asset_id, "expires": LINK_TTL_SECONDS},
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

    expires_at = now() + timedelta(seconds=LINK_TTL_SECONDS)
    if cached is None:
        db.add(PluginPublicLink(asset_id=asset_id, instance_id=instance.id, url=url, expires_at=expires_at))
    else:
        cached.url, cached.expires_at = url, expires_at
    db.commit()
    return url, instance.name
