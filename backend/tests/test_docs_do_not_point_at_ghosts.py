"""棘轮:**文档里指到的代码路径必须真的存在**。

文档腐烂不报错,只是把读的人送到一个不存在的地方 —— 而这比没有指引更糟:他会以为是自己
找不到,翻半天才发现文件早就搬了。发现时有三处:

· `docs/MAINTENANCE_HOTSPOTS.md` 指 `backend/app/ai/agent/host.py`(早搬到 domain/agent);
· `docs/adr/0006` 指 `plugins/migrations.py`(在 backend/app/domain/plugins/ 下);
· `docs/ARCHITECTURE.md` 用 `frontend/.../playback/sceneModel.ts` 省略中段,而省略号让人
  没法直接跳过去 —— 写全。

只查**代码路径**,不查散文里的概念:路径是机器能证伪的,而"这一段说得对不对"不是。

**扫描面必须自己长。** 第一版把顶层目录(`backend|frontend|electron|plugins|scripts|website`)
和后缀(`tsx|mdx|mjs|cjs|json|css|py|ts|md`)手写在正则里 —— 于是 `agent-sidecar/`、
`contracts/`、`browser-extension/`、`build/`、`test/`、`.github/` 整片不在扫描面内,
`.yml`/`.sh`/`.spec`/`.html` 也一样。这不是「漏了一个」,是**清单会在下一次加目录时失效**,
而没有人会记得回来改它。现在顶层目录问 git 要(仓库里真有什么就是什么),后缀不再枚举。
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

RATCHET = True

ROOT = pathlib.Path(__file__).resolve().parents[2]

#: 这些路径**不在仓库里,而且本该如此**,每条都要写清为什么 —— 这是豁免,不是忽略。
ALLOWLIST = {
    # electron-builder 的 extraResources 条目:`"to"` 说的是**打包后应用里**的位置。
    "agent-sidecar/sidecar.cjs",
    # 占位符,意思是「随便哪份契约」,不指某个文件。
    "contracts/xxx.json",
    # 审计报告里记的是「它曾经在,已核实为未跟踪的本地构建产物并删掉了」—— 报告说的就是
    # 它不该存在。留着这条比改报告诚实。
    "backend/mosael-backend.spec",
}


def _top_level_dirs(root: pathlib.Path) -> list[str]:
    """仓库里**真有**的顶层目录。手写这份清单是上一版失守的地方。"""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")
    return sorted({one.split("/")[0] for one in listed if "/" in one})


def _path_re(top_level: list[str]) -> re.Pattern[str]:
    """看起来像仓库内代码文件的东西。

    后缀**不枚举**:一个点加 1-5 位字母数字收尾,后面不许再跟单词字符或点。上一版列了 9 种
    后缀并特意把 `tsx` 排在 `ts` 前面(否则 `.tsx` 被截成 `.ts`,报一个假路径)—— 那份排序
    注释本身就是「枚举会出错」的证据。贪婪匹配到最后一个点,`preload.bundle.cjs` 整段拿下。
    """
    alternatives = "|".join(re.escape(one) for one in top_level)
    return re.compile(
        rf"(?<![\w/])((?:{alternatives})/[\w./-]+\.[A-Za-z0-9]{{1,5}})(?![\w.])"
    )


def _docs() -> list[pathlib.Path]:
    found = list((ROOT / "docs").rglob("*.md"))
    found += [ROOT / "README.md", ROOT / "README.zh-CN.md", ROOT / "CLAUDE.md"]
    return [one for one in found if one.exists()]


def _missing_code_paths(
    root: pathlib.Path, text: str, *, top_level: list[str] | None = None
) -> list[str]:
    # 构建产物可以尚未生成,但必须有真实的构建声明。不能按 .bundle.cjs 后缀
    # 一概豁免,否则拼错的产物路径也会被放过。
    scripts = json.loads((root / "package.json").read_text(encoding="utf-8"))["scripts"]
    outputs = {
        output
        for command in scripts.values()
        for output in re.findall(r"--outfile=([\w./-]+)", command)
    }
    pattern = _path_re(top_level if top_level is not None else _top_level_dirs(root))
    return [
        path
        for path in sorted(set(pattern.findall(text)))
        if path not in outputs and path not in ALLOWLIST and not (root / path).exists()
    ]


def test_文档里的代码路径都还在() -> None:
    top_level = _top_level_dirs(ROOT)
    # 扫描面自己也要有人看着:问 git 要的时候拿到空清单,下面那句 assert 天然为真。
    assert {"backend", "frontend", "agent-sidecar", "contracts"} <= set(top_level), (
        f"顶层目录只认出 {top_level} —— 仓库结构变了,还是 git 没答话?"
    )
    ghosts: list[str] = []
    for doc in _docs():
        text = doc.read_text(encoding="utf-8")
        for path in _missing_code_paths(ROOT, text, top_level=top_level):
            ghosts.append(f"{doc.relative_to(ROOT)} → {path}")
    assert not ghosts, "文档指到了不存在的文件(搬过家或改了名):\n  " + "\n  ".join(ghosts)


def test_干净检出允许已声明的产物但仍拒绝失效路径(tmp_path: pathlib.Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {"build:preload": "esbuild electron/preload.cjs --outfile=electron/preload.bundle.cjs"},
    }), encoding="utf-8")
    (tmp_path / "electron").mkdir()
    (tmp_path / "electron" / "preload.cjs").write_text("", encoding="utf-8")
    found = _missing_code_paths(
        tmp_path,
        " ".join([
            "`electron/preload.cjs`", "`electron/preload.bundle.cjs`",
            "`electron/typo.bundle.cjs`", "`electron/deleted.cjs`",
        ]),
        top_level=["electron"],
    )
    assert found == ["electron/deleted.cjs", "electron/typo.bundle.cjs"]


def test_后缀不再枚举_没列过的那些也在扫描面内(tmp_path: pathlib.Path) -> None:
    """上一版只认 9 种后缀,`.yml`/`.sh`/`.spec` 指到哪儿都不报。"""
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {}}), encoding="utf-8")
    found = _missing_code_paths(
        tmp_path,
        "`.github/workflows/ci.yml` `scripts/notarize.sh` `backend/x.spec` `frontend/a.tsx`",
        top_level=[".github", "backend", "frontend", "scripts"],
    )
    assert found == [
        ".github/workflows/ci.yml",
        "backend/x.spec",
        "frontend/a.tsx",
        "scripts/notarize.sh",
    ]


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
