"""棘轮:**文档里指到的代码路径必须真的存在**。

文档腐烂不报错,只是把读的人送到一个不存在的地方 —— 而这比没有指引更糟:他会以为是自己
找不到,翻半天才发现文件早就搬了。发现时有三处:

· `docs/MAINTENANCE_HOTSPOTS.md` 指 `backend/app/ai/agent/host.py`(早搬到 domain/agent);
· `docs/adr/0006` 指 `plugins/migrations.py`(在 backend/app/domain/plugins/ 下);
· `docs/ARCHITECTURE.md` 用 `frontend/.../playback/sceneModel.ts` 省略中段,而省略号让人
  没法直接跳过去 —— 写全。

只查**代码路径**,不查散文里的概念:路径是机器能证伪的,而"这一段说得对不对"不是。
"""

from __future__ import annotations

import pathlib
import re
import json

RATCHET = True

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: 反引号里、看起来像仓库内代码文件的东西。**后缀按长到短排**(tsx 在 ts 前面)——
#: 反过来的话 `.tsx` 会被截成 `.ts`,于是报一个不存在的路径,而那是假警报。
PATH_RE = re.compile(
    r"(?<![\w/])((?:backend|frontend|electron|plugins|scripts|website)/[\w./-]+"
    r"\.(?:tsx|mdx|mjs|cjs|json|css|py|ts|md))"
)


def _docs() -> list[pathlib.Path]:
    found = list((ROOT / "docs").rglob("*.md"))
    found += [ROOT / "README.md", ROOT / "README.zh-CN.md"]
    return [one for one in found if one.exists()]


def _missing_code_paths(root: pathlib.Path, text: str) -> list[str]:
    # 构建产物可以尚未生成,但必须有真实的构建声明。不能按 .bundle.cjs 后缀
    # 一概豁免,否则拼错的产物路径也会被放过。
    scripts = json.loads((root / "package.json").read_text(encoding="utf-8"))["scripts"]
    outputs = {
        output
        for command in scripts.values()
        for output in re.findall(r"--outfile=([\w./-]+)", command)
    }
    return [
        path for path in sorted(set(PATH_RE.findall(text)))
        if path not in outputs and not (root / path).exists()
    ]


def test_文档里的代码路径都还在() -> None:
    ghosts: list[str] = []
    for doc in _docs():
        text = doc.read_text(encoding="utf-8")
        for path in _missing_code_paths(ROOT, text):
            ghosts.append(f"{doc.relative_to(ROOT)} → {path}")
    assert not ghosts, "文档指到了不存在的文件(搬过家或改了名):\n  " + "\n  ".join(ghosts)


def test_干净检出允许已声明的产物但仍拒绝失效路径(tmp_path: pathlib.Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {"build:preload": "esbuild electron/preload.cjs --outfile=electron/preload.bundle.cjs"},
    }), encoding="utf-8")
    (tmp_path / "electron").mkdir()
    (tmp_path / "electron" / "preload.cjs").write_text("", encoding="utf-8")
    assert _missing_code_paths(tmp_path, " ".join([
        "`electron/preload.cjs`", "`electron/preload.bundle.cjs`",
        "`electron/typo.bundle.cjs`", "`electron/deleted.cjs`",
    ])) == ["electron/deleted.cjs", "electron/typo.bundle.cjs"]


def test_发布文档列的状态和权威清单一致() -> None:
    """状态清单是手抄进文档的,而抄漏/抄多都不报错。文档里曾经有个 `prepared` ——
    代码里从来没有过这个状态。"""
    from app.domain.publish.worker import TASK_STATUSES

    text = (ROOT / "docs" / "PUBLISHING.md").read_text(encoding="utf-8")
    match = re.search(r"回报富状态:`([a-z_/]+)`", text)
    assert match, "PUBLISHING.md 里那行状态清单不见了(改了格式就把这条一起改)"
    documented = set(match.group(1).split("/"))
    assert documented == set(TASK_STATUSES), (
        f"文档多出:{sorted(documented - set(TASK_STATUSES))};"
        f"文档缺少:{sorted(set(TASK_STATUSES) - documented)}"
    )
