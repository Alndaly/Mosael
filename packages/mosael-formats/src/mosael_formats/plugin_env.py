"""插件子进程环境里**宿主占着的名字** —— 清单里的配置 / 凭据键不能用它们。

进程插件和 MCP 的 stdio 插件起的都是插件的子进程,宿主给一份最小环境(见 backend 的
domain/plugins/child_env.base_env)。插件自己声明的配置 / 凭据也注入这份环境(键大写化),
**同名就会盖掉宿主给的**:一个叫 `path` 的配置项会把 PATH 换成用户填的一个文件路径,插件连解释器
都找不到。所以这些名字在清单校验时就挡住 —— 这是清单格式的一条规则,放在这里,装包和上架过的是同一条。
"""

from __future__ import annotations

#: 所有平台都给的三个。
BASE_KEYS = ("PATH", "HOME", "LANG")

#: Windows 上**没有它们子进程就起不来**的那几个。Python 初始化要 SYSTEMROOT(否则连随机数都拿
#: 不到),Node 要它做 DNS,npm 要 APPDATA / LOCALAPPDATA 放缓存,TEMP 是一切临时文件的去处。
WINDOWS_ESSENTIALS = (
    "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "PATHEXT", "TEMP", "TMP",
    "APPDATA", "LOCALAPPDATA", "USERPROFILE", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
)

#: 宿主和插件之间的约定变量(产出目录、持久目录、取消文件、语言……)都用这个前缀。
HOST_PREFIX = "MOSAEL_"


def is_reserved(key: str) -> bool:
    """这个配置 / 凭据键大写之后会不会盖掉宿主给的变量。**按所有平台算**:清单是跨平台的。"""
    upper = key.upper()
    return upper in BASE_KEYS or upper in WINDOWS_ESSENTIALS or upper.startswith(HOST_PREFIX)


__all__ = ["BASE_KEYS", "HOST_PREFIX", "WINDOWS_ESSENTIALS", "is_reserved"]
