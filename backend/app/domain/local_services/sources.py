"""「让 Mosael 装」从哪儿下(ADR 0041 §4):pip 源、PyTorch 源、GitHub 镜像前缀 —— 都在「管理 → 下载源」里,部署级。

宿主把它们算成地址交给插件(`service_plan` / `service_install` / `service_add_nodes` 输入里的 `sources`),插件不必自己带
「镜像」配置项(和 plugins/package_sources 同一个道理:镜像是这台机器、这个人的网络状况,不是插件的业务配置):

- `pip_index_url`:装 ComfyUI 的依赖(Apple 芯片 Mac 上 PyTorch 也从这里来);空 = 官方 PyPI;
- `pytorch_index_url`:装 CUDA 版 PyTorch 的 simple 索引根地址(下面按 `cu130` 分频道);总有一个地址,空的设置就是官方;
- `github_mirror`:下 GitHub 上钉死的压缩包时接在前面的前缀;空 = 直连。压缩包按 sha256 校验,镜像换不了内容。

**代理不在这里**:插件进程的环境里本来就是这个连接的出站代理(plugins/egress,缺省跟着 Mosael 的全局设置),下载、pip 都认它。
HuggingFace 的镜像沿用现有那一项设置,装的时候用不到。
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.ai.runtime import config as runtime_config
from app.core.i18n import tr
from app.domain.plugins.errors import PluginDomainError

_PYTORCH_LABELS = {"pytorch": "pkgSource_pytorchOfficial", "nju": "pkgSource_nju"}


def for_plugin() -> dict[str, str]:
    """交给插件的那三个地址(按「管理 → 下载源」此刻的设置)。"""
    current = runtime_config.get()
    return {
        "pip_index_url": current.pip_index_url,
        "pytorch_index_url": current.pytorch_index_url,
        "github_mirror": current.github_mirror or "",
    }


def labels() -> dict[str, str]:
    """三项此刻在界面上叫什么(安装计划在每个下载地址旁边写明它被哪一项改写了):`pip`、`pytorch` 是预设的名字或自填的地址,
    `github` 是前缀本身(空 = 没设,直连 GitHub)。"""
    from app.domain.plugins import package_sources

    current = runtime_config.get()
    key = (current.pytorch_index or "").strip() or runtime_config.OFFICIAL_PYTORCH
    return {
        "pip": package_sources.choice_label("pypi", current.pip_index or ""),
        "pytorch": tr(_PYTORCH_LABELS[key]) if key in _PYTORCH_LABELS else key,
        "github": current.github_mirror or "",
    }


def _http_url(value: str) -> bool:
    parts = urlsplit(value)
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def normalize_pytorch_index(choice: str) -> str:
    """保存前的校验:空(= 官方)、预设 key,或者一个 http(s) 地址(simple 索引的根,末尾的 `/` 去掉)。"""
    choice = (choice or "").strip()
    if not choice or choice in runtime_config.PYTORCH_INDEXES:
        return "" if choice == runtime_config.OFFICIAL_PYTORCH else choice
    if _http_url(choice):
        return choice.rstrip("/")
    raise PluginDomainError("pluginErr_packageSourceUrl", url=choice)


def normalize_github_mirror(prefix: str) -> str:
    """保存前的校验:空(= 直连),或者一个 http(s) 地址,存成以 `/` 结尾的前缀(原地址直接接在后面)。"""
    prefix = (prefix or "").strip()
    if not prefix:
        return ""
    if not _http_url(prefix):
        raise PluginDomainError("pluginErr_packageSourceUrl", url=prefix)
    return prefix if prefix.endswith("/") else f"{prefix}/"


def pytorch_presets() -> list[dict[str, str]]:
    """界面下拉里 PyTorch 源的预设:key、名字、地址。官方那一项的地址给空串、名字里写明是哪个站 —— 和 pip 那一行同一个约定
    (空值 = 官方,界面的下拉据此认出「官方」那一项),存的也是空串(见 normalize_pytorch_index)。"""
    return [{"value": key, "label": tr(_PYTORCH_LABELS.get(key, key)),
             "url": "" if key == runtime_config.OFFICIAL_PYTORCH else url}
            for key, url in runtime_config.PYTORCH_INDEXES.items()]


__all__ = ["for_plugin", "labels", "normalize_github_mirror", "normalize_pytorch_index", "pytorch_presets"]
