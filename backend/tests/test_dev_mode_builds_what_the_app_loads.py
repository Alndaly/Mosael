"""棘轮:**桌面端运行时要加载的东西,开发态必须先构建好、并且跟着改动重建。**

`.gitignore` 里写着「dev 脚本(frontend 的 electron:dev)里这些 bundle 都要构建到位,否则跑
起来会缺少桌面桥、发布执行器或系统能力层」—— 而写下这句话的时候它就已经不成立了:

· **sidecar 根本不构建。** `agent-sidecar/dist/sidecar.cjs` 只在 `build:mac`/`dist:mac` 里出现。
  新克隆跑 `pnpm dev`,智能体那一栏直接起不来,而错误是「sidecar 退出」这种指向别处的话;
· **system 构建一次就不再管。** `electron/system/*.ts` 改了在开发态**完全没有反应** ——
  没有报错,没有警告,只是你的改动不生效,于是人会去怀疑自己的代码。

判据不是一份「哪些要构建」的清单(那种清单会在下一次加 `build:*` 时失效),而是:
**根 package.json 里每一个 `build:*` 脚本,要么被 `electron:dev` 接住,要么在下面写明为什么
不用接。** 加一个新的打包步骤时,这条会立刻问你它在开发态怎么办。
"""

from __future__ import annotations

# 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
RATCHET = True

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: 这些 `build:*` **不该**被开发态接住,每条写清为什么。
EXEMPT = {
    # 开发态直接跑源码(dev:backend 的 uvicorn --reload),不走 PyInstaller 冻结包。
    "build:backend",
    # 开发态是 Vite dev server(electron:dev 的第一栏),不走静态产物。
    "build:frontend",
    # 浏览器扩展是**另一个宿主**里的东西(Chrome 加载 browser-extension/dist),
    # 不在桌面端进程里,也不由 electron:dev 拉起。
    "build:extension",
    # 它不是一个「产物步骤」,是**整条打包流水线**(它自己调上面那些)。开发态要的是
    # 里面那几步,不是它。
    "build:mac",
}


def _scripts(relative: str) -> dict[str, str]:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))["scripts"]


def test_每个打包步骤在开发态都有着落() -> None:
    root = _scripts("package.json")
    dev = _scripts("frontend/package.json")["electron:dev"]

    missing: list[str] = []
    for name in sorted(one for one in root if one.startswith("build:")):
        if name in EXEMPT:
            continue
        suffix = name.split(":", 1)[1]
        if name not in dev:
            missing.append(f"{name}:开发态启动时不构建 —— 新克隆里这个产物压根不存在")
        if f"watch:{suffix}" not in root:
            missing.append(f"watch:{suffix}:根 package.json 里没有这个脚本")
        elif f"watch:{suffix}" not in dev:
            missing.append(f"watch:{suffix}:存在但没接进 electron:dev —— 改了不重建,而且不报错")

    assert not missing, (
        "桌面端开发态和它要加载的东西对不上:\n  "
        + "\n  ".join(missing)
        + "\n把它接进 frontend/package.json 的 electron:dev(构建一次 + 一路 watch),"
        "或者在本测试的 EXEMPT 里写明为什么不用接。"
    )


def test_豁免名单里的名字都还存在() -> None:
    """豁免一个已经不存在的脚本 = 在守一个不存在的约定,而且会掩护下一个同名脚本。"""
    root = _scripts("package.json")
    assert not sorted(EXEMPT - set(root)), f"EXEMPT 里这些脚本已经没了:{sorted(EXEMPT - set(root))}"
