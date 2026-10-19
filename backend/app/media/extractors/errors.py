"""站点适配器向上抛的两类错误。

**为什么不直接抛 `YtdlpError`。** 适配器层(`media/extractors`)不该反向 import `media/ytdlp` ——
那会把两个包卷成环(见 `tests/test_import_layering.py`)。这里只带**文案 key 与参数**,翻成给用户看的
那句话是 `ytdlp.classify` 的事。

两类分开,因为它们的含义不同:

- `SiteAdapterPending`:站点认出来了,但页面解析还没写(骨架阶段)。别的适配器以后还会走这条路。
- `SiteAdapterError`:解析写了、但这次页面取不到地址(页面太大 / 没有 packed 块 / 脚本解不开)。
  每一处都带自己的 key,出口按请求语言翻,不会退化成一句泛泛的「取不到」。
"""
from __future__ import annotations


class SiteAdapterPending(RuntimeError):
    """站点认领了,但页面解析还没接入。

    适配器层只表达「哪一步没做」,**不 import `media/ytdlp`**。翻成给用户看的那句话
    在 `ytdlp.classify`:它把这里带上来的站点名变成一个带 key 的 `YtdlpError`。
    """

    def __init__(self, site: str) -> None:
        self.site = site
        super().__init__(f"{site}: page parsing is not implemented yet")


class SiteAdapterError(RuntimeError):
    """页面解析失败:**明确是哪一种**,不是恰好抛出来的某个底层异常。

    `key` 是 `core/i18n` 里的一条 `urlImportErr_*` 文案;`params` 是那条文案的参数(站点名等)。
    `classify` 原样把它们抬成 `YtdlpError`,于是 `probe` / `download` 的用户看到的是一句能照着做的话。
    """

    def __init__(self, key: str, **params: object) -> None:
        self.key = key
        self.params = params
        super().__init__(f"{key}: {params}")
