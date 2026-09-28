"""把一份**本地素材**变成一条公网可下载的地址 —— 交给声明了这个能力的插件去做。

## 它解决的那个断链

Mosael 是本地优先的:素材在用户自己的盘上,没有公网地址。而有些供应商的某些角色**只收链接**
—— 方舟 Seedance 的参考视频就是一例(参考**图**可以走 Base64,参考**视频**不行,官方文档
明写),视频编辑、视频续写那两条路上的源视频同理。

此前这条路直接断在提交前:界面上拦一句"请改用一条公网直链"。**那是把问题退回给用户** ——
他得自己找个对象存储、自己传、自己签链接、再粘回来,而这四步里每一步都可能做错。

现在多一步:提交时看见这种角色带的是本地素材,就找一个**声明了 `public_url` 能力**的插件
(随应用内置的「对象存储」插件,一个连接对一家的一个桶;第三方插件也可以声明它),
让它传上去并交回一条限时直链。用户那一侧只是多等几秒。

## 为什么按声明找,而不是按工具名猜

靠 `*_upload` 这种后缀去猜的话,任何一个叫这个名字的工具都会被当成对象存储 ——
而猜错的表现是**把用户的素材传去了别的地方**。所以插件在清单里显式声明
`"provides": ["public_url"]`,宿主只认这个(见 plugins/manifest.Manifest.provides)。

## 用哪一家

- **只看发起人自己的实例。** 存储实例是个人的(桶和密钥都是他的);此前查的是整个部署里的全部
  实例,多人部署时 A 的素材会用 B 的桶和密钥传上去 —— 文件落在别人的桶里,钱也记在别人头上。
- **只看配好的。** 桶名、密钥缺一项的不算候选。
- **配好了一家就用它;配好了几家,用他定为默认的那家**(「设置 → 能力提供方 → 素材外链」,
  存在 PluginCapabilityDefault;挑法是 domain/capabilities 那一份,和文档解析共用)。**没定就当场问,不替他挑** —— 此前按实例名的字母序取第一个,
  谁被用上取决于它叫什么。
- 上传工具由工具自己声明(清单里工具上的 `provides`),不按 `_upload` 后缀猜。

## 同一份素材不重复传

链接按(素材, 存储实例)记住(PluginPublicLink),还在有效期里就直接用。此前同一份参考视频
点两次生成就传两次。

## 失败要说得出口

每一种失败对用户意味着不同的下一步,所以分开说:

- **没有自己的连接**:告诉他去「对象存储」建一个、支持哪几家(而不是"请自行上传到公开地址");
- **装了但没配好**:点名是哪一个实例、缺什么(桶名?密钥?);
- **配好了几家却没定默认**:点名是哪几家,说去哪儿定;
- **插件版本太旧**(包上声明了能力、却没有工具认领):去插件页更新;
- **传失败**:把插件自己的话带出来(桶不存在、密钥没权限、网络不通),并说清素材是哪一份。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING

from app.core.i18n import tr
from app.domain import capabilities
from app.domain.capabilities import Capability, CapabilityUnavailable

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

#: 插件在清单里声明的那个能力名。
PUBLIC_URL = "public_url"
#: 交回来的直链要活多久。一次生成任务在**提交时**就把文件取走,给足余量。
LINK_TTL_SECONDS = 6 * 3600
#: 复用一条缓存的直链时,至少还要剩这么久 —— 供应商排队到真正取文件,中间可能隔一阵。
REUSE_MARGIN = timedelta(hours=1)


class NoUploader(CapabilityUnavailable):
    """没有可用的上传插件。消息是给用户看的,要说清下一步做什么。带文案 key(`genErr_*`)。"""


#: 素材外链这项能力的契约。挑哪一家、挑不出来时说什么都在 domain/capabilities 那一份挑法里;
#: 这里只给文案和「只有一家配好就不问直接用」(装了对象存储就是为这个)。没有内置实现。
CAPABILITY = Capability(
    name=PUBLIC_URL,
    label_key="capability_public_url",
    description_key="capability_public_url_desc",
    error=NoUploader,
    none_key="genErr_noUploader",
    incomplete_key="genErr_uploaderIncomplete",
    ambiguous_key="genErr_uploaderAmbiguous",
    outdated_key="genErr_uploaderOutdated",
)


def choose_uploader(db: "Session", owner_user_id: str | None, asset_name: str):
    """挑出这一次用哪一家存储,挑不出来时抛 `NoUploader`(消息给用户看)。"""
    provider = capabilities.choose(db, owner_user_id, CAPABILITY, asset=asset_name)
    return provider.instance, provider.tool


def _granted_seconds(output: dict) -> int:
    """这条链接**实际**活多久:插件在 `expires_in` 里说了就按它的(可能比要的短 —— 某家的上限、插件自己的
    规矩),没说才按要的算。此前一律按要的 6 小时记,链接早失效了还被当成能用,生成到对面取文件时才 403。"""
    raw = output.get("expires_in")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
        return LINK_TTL_SECONDS
    return int(min(raw, LINK_TTL_SECONDS))


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
        raise NoUploader("genErr_uploadFailed", plugin=instance.name, asset=asset_name, detail=str(exc)) from exc

    output = invocation.output or {}
    if invocation.status != "succeeded":
        detail = str(output.get("error") or invocation.error or tr("genErr_pluginNoReason"))
        raise NoUploader("genErr_uploadFailed", plugin=instance.name, asset=asset_name, detail=detail)
    url = str(output.get("url") or output.get("public_url") or "").strip()
    if not url:
        raise NoUploader("genErr_uploadNoUrl", plugin=instance.name)

    expires_at = now() + timedelta(seconds=_granted_seconds(output))
    if cached is None:
        db.add(PluginPublicLink(asset_id=asset_id, instance_id=instance.id, url=url, expires_at=expires_at))
    else:
        cached.url, cached.expires_at = url, expires_at
    db.commit()
    return url, instance.name
