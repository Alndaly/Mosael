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


def persist(
    db: Session,
    instance: PluginInstance,
    state: dict[str, Any],
    *,
    baseline: dict[str, str],
    notify: bool = True,
) -> None:
    """把插件交回的状态按声明分流落库。空的就什么都不做。

    `baseline` 是**这次调用开始时**注入给插件的那一份值(instances.secrets_for)。一个键只有在
    库里的值**还是它**时才写回 —— 比较交换,不是后写者赢:

    同一个连接上两次调用并发(工作流的并行分支、智能体连着调),各自拿同一个旧 refresh_token 去换。
    会轮换 refresh_token 的服务(百度网盘)上,先换的那次拿到 RT1,后换的那次拿到 RT2、同时让 RT1
    作废。此前谁后**结束**谁写 —— 先换的那次若结束得晚,就把已作废的 RT1 盖在 RT2 上,之后每一次调用
    都报令牌失效,用户得重新走一遍授权。调用途中用户自己在插件页改了这一格,也是同一个道理:他的新值
    不该被一次旧调用的状态盖掉。被跳过的键记一条日志。

    `notify=False`:这份状态是插件在**替宿主做事的途中**交回来的(刷新目录、做一次生成),
    不该反过来再触发一次「实例变了,去重新问一遍插件」—— 那会在一次调用里嵌套起另一次调用。
    """
    if not state:
        return
    from app.domain.plugins import instances as inst

    manifest = inst.manifest_for(db, instance)
    credential_keys = {spec.key for spec in manifest.credentials}
    config_keys = {spec.key for spec in manifest.config}

    unknown = sorted(set(state) - credential_keys - config_keys)
    if unknown:
        raise PluginDomainError("pluginErr_stateUnknownKeys", keys=", ".join(unknown))
    too_long = sorted(key for key, value in state.items() if len(str(value)) > MAX_VALUE_CHARS)
    if too_long:
        raise PluginDomainError("pluginErr_stateTooLong", limit=MAX_VALUE_CHARS, keys=", ".join(too_long))

    current = inst.secrets_for(db, instance)
    moved = sorted(key for key in state if current.get(key, "") != baseline.get(key, ""))
    if moved:
        logger.info("插件 %s 的 %s 在这次调用途中被别处改过,不用这次交回的值盖掉", instance.id, ", ".join(moved))
        state = {key: value for key, value in state.items() if key not in moved}
        if not state:
            return

    credentials = {key: str(value) for key, value in state.items() if key in credential_keys}
    config = {key: value for key, value in state.items() if key in config_keys and key not in credential_keys}
    if credentials:
        inst.set_credentials(db, instance, credentials, notify=notify)
    if config:
        inst.set_config(db, instance, config, notify=notify)
    logger.info("插件 %s 记住了 %d 项状态", instance.id, len(state))


__all__ = ["MAX_VALUE_CHARS", "persist"]
