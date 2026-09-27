"""插件子进程的**宿主那一半**环境:哪些变量由宿主给、哪些名字插件不能占。

进程插件(runtime)和 MCP 的 stdio 插件(mcp_bridge)起的都是插件的子进程,两边给的「最小环境」
必须是同一份 —— 此前各写一遍,MCP 那份漏了 Windows 上起进程必需的那几个(见 WINDOWS_ESSENTIALS),
于是 `npx` / `uvx` 起的 MCP 插件在 Windows 上一个也起不来,而进程插件那边早就修过了。

插件自己声明的配置 / 凭据也注入这份环境(键大写化,见 instances.process_env),**同名就会盖掉宿主给的**:
一个叫 `path` 的配置项会把 PATH 换成用户填的一个文件路径,插件连解释器都找不到。所以这些名字在清单
解析时就挡住(见 manifest 与 `is_reserved`),不留到跑的时候才出一个看不懂的错。

**哪些名字插件不能占**是清单格式的一条规则,住在 `mosael_formats.plugin_env`(桌面后端与社区服务
共用,ADR 0026);这里只剩「宿主实际给哪些值」这一半。
"""

from __future__ import annotations

import os
import sys

from mosael_formats.plugin_env import BASE_KEYS, HOST_PREFIX, WINDOWS_ESSENTIALS, is_reserved


def base_env() -> dict[str, str]:
    """插件子进程的基础环境:PATH / HOME / LANG,Windows 上再加 WINDOWS_ESSENTIALS。"""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
    }
    if sys.platform == "win32":
        upper = {key.upper(): value for key, value in os.environ.items()}
        env.update({key: upper[key] for key in WINDOWS_ESSENTIALS if key in upper})
    return env


__all__ = ["BASE_KEYS", "HOST_PREFIX", "WINDOWS_ESSENTIALS", "base_env", "is_reserved"]
