"""插件把一点东西**记到下次调用**。

插件**进程**是无状态的:环境变量进、JSON 出,跑完就没了,插件自己没有任何写回的手段。对纯计算的工具这没问题,对**要续期的凭据**就是个
死结 —— 百度网盘的 access_token 三十天到期,插件拿 refresh_token 换一个新的很容易,难的是
换完之后没地方放。结果是每个 OAuth 类插件都只能让用户三十天回来粘一次,或者干脆不做刷新。

所以给响应加一个 `state` 槽:插件写什么,宿主替它记住,下次调用原样注入回环境变量。

**只能写清单里声明过的键。** 三条理由:

  · 有界 —— 插件不能凭空往数据库里塞任意键值;
  · 分流 —— 声明成 credential 的进加密凭据库,声明成 config 的进明文配置。刷新出来的
    令牌和「上次同步到哪」不该存在同一个地方;
  · 看得见 —— 用户在插件页看得到这些字段,能自己改、自己清空。一个插件在背后攒一份
    用户看不见也删不掉的状态,是不该有的东西。

写了没声明的键**直接失败**,不是忽略。忽略的话插件以为自己存下了,下次拿到旧值,而错误
表现在几十分钟之后的另一个地方(「怎么又提示 token 过期」)。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import PluginInstance
from app.domain.plugins.errors import PluginDomainError

logger = logging.getLogger(__name__)

#: 单个值最长多少。凭据、游标、id —— 正常都是几十到几百字符。给一个上限是为了挡住
#: 「把整份响应缓存塞进 state」这种用法:那会让每次调用都重写一遍数据库。
MAX_VALUE_CHARS = 8192


def persist(db: Session, instance: PluginInstance, state: dict[str, Any]) -> None:
    """把插件交回的状态按声明分流落库。空的就什么都不做。"""
    if not state:
        return
    from app.domain.plugins import instances as inst

    manifest = inst.manifest_for(db, instance)
    credential_keys = {spec.key for spec in manifest.credentials}
    config_keys = {spec.key for spec in manifest.config}

    unknown = sorted(set(state) - credential_keys - config_keys)
    if unknown:
        raise PluginDomainError(f"插件想记住未声明的键: {', '.join(unknown)}")
    too_long = sorted(key for key, value in state.items() if len(str(value)) > MAX_VALUE_CHARS)
    if too_long:
        raise PluginDomainError(f"插件状态过长(上限 {MAX_VALUE_CHARS} 字符): {', '.join(too_long)}")

    credentials = {key: str(value) for key, value in state.items() if key in credential_keys}
    config = {key: value for key, value in state.items() if key in config_keys and key not in credential_keys}
    if credentials:
        inst.set_credentials(db, instance, credentials)
    if config:
        inst.set_config(db, instance, config)
    logger.info("插件 %s 记住了 %d 项状态", instance.id, len(state))


__all__ = ["MAX_VALUE_CHARS", "persist"]
