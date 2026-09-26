"""市场上的「更新」:索引许的是哪一版,下载地址真给的是哪一版。

用户撞到过的事:索引写 remotion 0.2.0,下载地址给的却还是 0.1.0。「更新」装回同一版,索引照旧
说 0.2.0 —— 「有新版」永远不消失,点多少次都一样。根上的修法在索引那头:官方索引是**发版产物**,
和插件包由同一次发版、从同一份源码生成,下载地址钉在那次发版的 tag 上(见
scripts/sync-plugin-registry.py 与 docs/RELEASING.md),许的就是给的。

这里是装的那一刻的**第二道**:索引是谁都能架的普通 JSON(见 registry),许诺和实物对不上的情况
不能只靠索引那头不犯错。所以:

- 「有新版」按**语义化版本的先后**判(versions),不按字符串不相等 —— 装着的比索引新时不叫更新;
- 从市场点「更新」时,下下来的包先读清单:**不比装着的新,就不装、不报「已更新」**,而是说清
  「新版本还没发布」,并记下这一条(PluginMarketHold),市场先别再对它说「有新版」;
- 记下的那条只对「同一份许诺」算数:索引许的版本或给的地址一变,或者过了时限,就不再算数。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.model_base import now
from app.db.models import PluginMarketHold, PluginPackage
from app.domain.plugins.versions import is_newer

#: 记下的「还没发布」多久之后不再算数。官方索引发新版时下载地址本身就会换(钉 tag),用不上它;
#: 它兜的是自己架的索引 —— 那种索引可能一直用同一个地址,而地址背后的包迟早会换成真正的新版,
#: 不设时限的话,那一版真发出来之后市场也再不提示了。
HOLD_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class UpdateState:
    """市场里一条已装的插件,此刻该不该说「有新版」。"""

    #: 索引许的版本比装着的新,而且没有被证实「还没发布」。
    available: bool
    #: 索引许的版本比装着的新,但点过「更新」、下下来的包并不比装着的新。
    unreleased: bool


def holds(db: Session) -> dict[str, PluginMarketHold]:
    """所有记下的「还没发布」,按插件 id。市场一屏读一次。"""
    return {hold.package_id: hold for hold in db.scalars(select(PluginMarketHold))}


def _holds_this_promise(hold: PluginMarketHold | None, entry: dict[str, Any]) -> bool:
    if hold is None or now() - hold.recorded_at > HOLD_TTL:
        return False
    return hold.advertised_version == str(entry.get("version") or "") and hold.download == str(entry.get("download") or "")


def state_of(entry: dict[str, Any], package: PluginPackage | None, hold: PluginMarketHold | None) -> UpdateState:
    """索引里的一条 + 这台机器上装着的那一版 → 有没有新版。

    随应用内置的不从市场更新(新版跟着应用来),永远不算。
    """
    if package is None or entry.get("bundled") is True:
        return UpdateState(available=False, unreleased=False)
    newer = is_newer(str(entry.get("version") or ""), package.version)
    held = newer and _holds_this_promise(hold, entry)
    return UpdateState(available=newer and not held, unreleased=held)


def not_released(db: Session, raw: dict[str, Any], *, advertised_version: str, download: str) -> bool:
    """从市场点「更新」下下来的包(`raw` 是包里的清单),是不是**并不比装着的新**。是的话记下来(不提交),返回真。

    只管从市场来的更新(`advertised_version` 非空):从链接装同一版是有意的重装,不拦。
    没装过的也不算 —— 那是安装,不是更新。
    """
    advertised_version = advertised_version.strip()
    if not advertised_version:
        return False
    plugin_id = str(raw.get("id") or "")
    served_version = str(raw.get("version") or "")
    package = db.get(PluginPackage, plugin_id)
    if package is None or is_newer(served_version, package.version):
        return False
    hold = db.get(PluginMarketHold, plugin_id)
    if hold is None:
        hold = PluginMarketHold(package_id=plugin_id, advertised_version="", download="", served_version="")
        db.add(hold)
    hold.advertised_version = advertised_version[:40]
    hold.download = download[:1000]
    hold.served_version = served_version[:40]
    hold.recorded_at = now()
    return True


def clear(db: Session, plugin_id: str) -> None:
    """装上了一版:之前记下的「还没发布」不再算数(不提交)。"""
    hold = db.get(PluginMarketHold, plugin_id)
    if hold is not None:
        db.delete(hold)


__all__ = ["HOLD_TTL", "UpdateState", "clear", "holds", "not_released", "state_of"]
