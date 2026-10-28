"""**随应用一起发**的插件(`plugins/bundled/`):装好、登记好,用户什么都不用做。

市场里的插件要用户去装(那一步省不掉:装插件 = 往他机器上放一份会被执行的代码,得让他看过权限)。
随应用发的不一样 —— 它就是应用的一部分,和后端、前端一起签名、一起发版。ComfyUI 从内核搬成插件
(ADR 0020)之后,用过它的人升级完不该发现「ComfyUI 不见了,要去市场找」。

这里只答「这一版带了哪些、在哪儿、内容指纹是什么」,**只读**;装进插件目录并登记是 bundled_install 的事。
分开是因为包登记(packages)卸载前要问「是不是随包的」,而安装又要用包登记 —— 写在一个模块里,
两个模块就互相 import 了(见 tests/test_import_layering)。

插件自己的持久目录(`MOSAEL_PLUGIN_DATA_DIR`)和实例、凭据都不在插件目录里,换目录伤不到它们。

**卸不掉**(见 packages.uninstall):卸了下次启动又装回来,那比「这个删不了」更让人困惑。
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from app.core.interpreter import is_frozen
from app.domain.plugins.migrations import CANONICAL_FILENAME

#: 装进插件目录后记内容指纹的文件。它不在清单里,不影响插件本身。
DIGEST_FILENAME = ".bundled-digest"


def bundled_root() -> Path:
    """这一版随包带的插件在哪儿。

    打包版:PyInstaller 把 `plugins/bundled` 带进了解包目录(见 package.json 的 build:backend
    `--add-data`);开发时:仓库根下的 `plugins/bundled`。
    """
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", "")) / "plugins" / "bundled"
    return Path(__file__).resolve().parents[4] / "plugins" / "bundled"


@dataclass(frozen=True)
class BundledPlugin:
    id: str
    source: Path

    @property
    def digest(self) -> str:
        """内容指纹。**用到才算**:只有启动对账要它。

        此前在 `plugins()` 里给每个随包插件现算一遍 —— 而 `plugins()` 还被插件页列表、市场、卸载
        判定拿来问「哪几个是随包的」,于是每次打开插件页都把 ComfyUI 整个目录读一遍、哈希一遍。
        """
        return _digest(self.source)


def _digest(root: Path) -> str:
    """整棵目录的内容指纹(路径 + 字节)。缓存目录不算 —— 跑过一次的插件会留下 __pycache__。"""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.name == DIGEST_FILENAME:
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def plugins() -> list[BundledPlugin]:
    """这一版带了哪些插件。目录不在(比如只拷了后端出来跑)就是一个都没有。只读清单,不碰别的文件。"""
    root = bundled_root()
    if not root.is_dir():
        return []
    found: list[BundledPlugin] = []
    for child in sorted(root.iterdir()):
        manifest = child / CANONICAL_FILENAME
        if not manifest.is_file():
            continue
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        found.append(BundledPlugin(id=str(raw["id"]), source=child))
    return found


def is_bundled(package_id: str) -> bool:
    return any(one.id == package_id for one in plugins())


__all__ = ["DIGEST_FILENAME", "BundledPlugin", "bundled_root", "is_bundled", "plugins"]
