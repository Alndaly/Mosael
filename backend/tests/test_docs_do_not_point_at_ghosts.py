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

    后缀**不枚举**:一个点加「字母打头的 1-5 位字母数字」收尾,后面不许再跟单词字符或点。
    上一版列了 9 种后缀并特意把 `tsx` 排在 `ts` 前面(否则 `.tsx` 被截成 `.ts`,报一个假路径)
    —— 那份排序注释本身就是「枚举会出错」的证据。贪婪匹配到最后一个点,
    `preload.bundle.cjs` 整段拿下。

    **后缀必须字母打头**:否则 `browser-extension/0.1.0` 这种「目录名 + 版本号」会被读成一个
    路径(`browser-extension` 是真的顶层目录,`.0` 像个后缀)—— 实测在 ARCHITECTURE.md 里
    误报过一次。仓库里没有任何一个后缀是数字打头的(`git ls-files` 核过)。
    """
    alternatives = "|".join(re.escape(one) for one in top_level)
    return re.compile(
        rf"(?<![\w/])((?:{alternatives})/[\w./-]+\.[A-Za-z][A-Za-z0-9]{{0,4}})(?![\w.])"
    )


def _docs() -> list[pathlib.Path]:
    found = list((ROOT / "docs").rglob("*.md"))
    found += [ROOT / "README.md", ROOT / "README.zh-CN.md", ROOT / "CLAUDE.md"]
    return [one for one in found if one.exists()]


def _ratchets() -> list[pathlib.Path]:
    """标了 RATCHET 的那些测试文件。

    **棘轮的 docstring 也是文档,而且是信息密度最高的那一批** —— 它写的是"为什么有这条、
    防的是哪次真实事故、挡不住什么"。它同样没有任何同步机制:实测 `typeScale.test.ts` 的
    说明写着"四档 text-ui-* 用 clamp() 跟视口联动",而 token 表里是六个、且是固定像素。
    散文没法测,但**它指到的路径可以** —— 那是这类文字能被机器守住的那一半。
    """
    found: list[pathlib.Path] = []
    for base, pattern, marker in (
        (ROOT / "backend" / "tests", "test_*.py", "RATCHET = True"),
        (ROOT / "frontend" / "src", "*.test.ts*", "export const RATCHET = true"),
    ):
        for path in sorted(base.rglob(pattern)):
            if marker in path.read_text(encoding="utf-8"):
                found.append(path)
    return found


def _ignored_by_git(root: pathlib.Path, paths: list[str]) -> set[str]:
    """`.gitignore` 说「这不是源码」的那些 —— 构建产物在干净检出上本来就不存在。

    此前这里解析根 `package.json` 里的 `--outfile=`。那份推导也是手写的扫描面:
    `agent-sidecar/dist/sidecar.cjs` 的声明在**子包**的 package.json 里(而且是相对路径),
    `frontend/dist/index.html` 根本没人写 —— Vite 的 outDir 用的是默认值。两条都在 CI 上红了,
    而本机因为构建过所以是绿的。

    `.gitignore` 才是这件事的权威:它逐条写明哪些路径是产物、为什么不入库。而且它**不会**
    顺手放过拼错的名字 —— 那几个 esbuild bundle 在 .gitignore 里是一个一个列的,
    `electron/typo.bundle.cjs` 不在其中。
    """
    if not paths:
        return set()
    listed = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--stdin"],
        input="\n".join(paths),
        capture_output=True,
        text=True,
        check=False,
    )
    return {line.strip() for line in listed.stdout.splitlines() if line.strip()}


def _missing_code_paths(
    root: pathlib.Path, text: str, *, top_level: list[str] | None = None
) -> list[str]:
    pattern = _path_re(top_level if top_level is not None else _top_level_dirs(root))
    candidates = [
        path
        for path in sorted(set(pattern.findall(text)))
        if path not in ALLOWLIST and not (root / path).exists()
    ]
    ignored = _ignored_by_git(root, candidates)
    return [path for path in candidates if path not in ignored]


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


def test_棘轮说明里指到的路径也都还在() -> None:
    """棘轮的 docstring 指到的文件必须存在 —— 它比散文更该守得住,因为读它的人正在改那段代码。"""
    ratchets = _ratchets()
    # 扫描面站得住:一个棘轮都没认出来的话,下面那句 assert 天然成立。
    assert len(ratchets) > 40, f"只认出 {len(ratchets)} 条棘轮 —— 标记的写法变了?"

    top_level = _top_level_dirs(ROOT)
    ghosts: list[str] = []
    for path in ratchets:
        # **这份文件自己除外。** 它的说明里逐条列着"搬过家的那三个路径",那是它存在的理由 ——
        # 要求它们存在,等于要求这条棘轮从没抓到过东西。(第一次跑这条测试时,唯一的三条
        # 报警正是它自己。)
        if path.name == "test_docs_do_not_point_at_ghosts.py":
            continue
        text = path.read_text(encoding="utf-8")
        # 只看开头那段说明,不看测试体:测试体里出现的路径常常是**故意造的假路径**
        # (tmp_path 的用例、变异验证的样例),那些本来就不该存在。
        head = text[: text.find("\nRATCHET") if "\nRATCHET" in text else min(len(text), 4000)]
        for one in _missing_code_paths(ROOT, head, top_level=top_level):
            ghosts.append(f"{path.relative_to(ROOT)} → {one}")
    assert not ghosts, "棘轮说明里指到了不存在的文件:\n  " + "\n  ".join(ghosts)


def test_干净检出允许已声明的产物但仍拒绝失效路径(tmp_path: pathlib.Path) -> None:
    """产物不在 ≠ 路径失效。判据是 `.gitignore` 认不认它,而不是它长得像不像产物。"""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    # 和仓库真实的 .gitignore 同一种写法:bundle 逐个列名,所以拼错的那个不在其中。
    (tmp_path / ".gitignore").write_text("dist/\nelectron/preload.bundle.cjs\n", encoding="utf-8")
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


def test_子包和默认出目录的产物也算数(tmp_path: pathlib.Path) -> None:
    """CI 上红的正是这两条:声明在子包里(相对路径),或者压根没人写(Vite 的默认 outDir)。"""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("dist/\n", encoding="utf-8")
    found = _missing_code_paths(
        tmp_path,
        "`agent-sidecar/dist/sidecar.cjs` `frontend/dist/index.html` `frontend/src/gone.tsx`",
        top_level=["agent-sidecar", "frontend"],
    )
    assert found == ["frontend/src/gone.tsx"]


def test_后缀不再枚举_没列过的那些也在扫描面内(tmp_path: pathlib.Path) -> None:
    """上一版只认 9 种后缀,`.yml`/`.sh`/`.spec` 指到哪儿都不报。"""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
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
