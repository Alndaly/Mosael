"""照着别家规范写的技能文件夹直接导进来,以及对话里附上压缩包 / 文件夹(ADR 0059)。

样例是维护者手上的两个真技能(fixtures/agent_skills),**文件夹名照原样**带中文和空格 —— 文件夹名只是外壳,
技能叫什么只认 SKILL.md 里的 `name`。它们还带着 OpenAI Codex 约定的 `agents/openai.yaml` 和 `references/`。
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from app.core.db import SessionLocal
from app.db.models import Asset
from app.domain.agent.skills import catalog, runtime
from tests.util import fresh_client

SAMPLES = Path(__file__).parent / "fixtures" / "agent_skills"
DIRECTOR = "authenticity-video-director 活人感skill"
STORYBOARD = "minimax-h3-video-prompt 分镜skill"


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _sample_files(*folders: str, prefix: str = "") -> dict[str, bytes]:
    """样例文件夹 → {相对路径: 内容},相对路径像浏览器 webkitRelativePath 那样从选中的那一层开始。"""
    out: dict[str, bytes] = {}
    for folder in folders:
        for path in sorted((SAMPLES / folder).rglob("*")):
            if path.is_file():
                out[f"{prefix}{path.relative_to(SAMPLES).as_posix()}"] = path.read_bytes()
    return out


def _upload_folder(client, url: str, files: dict[str, bytes], source_name: str = ""):
    return client.post(
        url,
        files=[("files", (Path(path).name, data)) for path, data in files.items()],
        data={"paths": list(files), "source_name": source_name},
    )


def _zip(entries: dict[str, bytes], symlinks: tuple[str, ...] = ()) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
        for name in symlinks:
            info = zipfile.ZipInfo(name)
            info.external_attr = 0o120777 << 16
            archive.writestr(info, "/etc/passwd")
    return buffer.getvalue()


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 80, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


# ---------------------------------------------------------------- 设置页导入


def test_单独导入一个样例文件夹_名字照SKILL_md_附带文件都在_显示名取自openai_yaml() -> None:
    client = fresh_client()
    ws = _workspace(client)
    response = _upload_folder(client, f"/api/workspaces/{ws}/skill-imports", _sample_files(DIRECTOR), source_name=DIRECTOR)
    assert response.status_code == 200, response.text
    [item] = response.json()["skills"]
    assert item["name"] == "authenticity-video-director"
    assert item["folder"] == DIRECTOR
    assert item["title"] == "Authenticity Video Director"
    paths = {one["path"] for one in item["files"]}
    assert {"SKILL.md", "agents/openai.yaml", "references/diagnosis.md", "references/portrait-airiness.md"} <= paths
    assert len(paths) == 7
    assert response.json()["source_name"] == DIRECTOR


def test_选父目录一起导入两个技能() -> None:
    client = fresh_client()
    ws = _workspace(client)
    files = _sample_files(DIRECTOR, STORYBOARD, prefix="skills/")
    response = _upload_folder(client, f"/api/workspaces/{ws}/skill-imports", files)
    assert response.status_code == 200, response.text
    skills = {one["name"]: one for one in response.json()["skills"]}
    assert set(skills) == {"authenticity-video-director", "minimax-h3-video-prompt"}
    assert len(skills["minimax-h3-video-prompt"]["files"]) == 9
    assert response.json()["source_name"] == "skills"


def test_压缩包多一层顶级目录_带着__MACOSX和DS_Store_装好后原样落地_运行时读得到references() -> None:
    client = fresh_client()
    ws = _workspace(client)
    entries = _sample_files(DIRECTOR, STORYBOARD, prefix="skills/")
    entries["skills/.DS_Store"] = b"\x00\x00\x00\x01Bud1"
    entries[f"__MACOSX/skills/{DIRECTOR}/._SKILL.md"] = b"\x00\x05\x16\x07"
    entries[f"skills/{STORYBOARD}/references/.DS_Store"] = b"\x00"
    staged = client.post(f"/api/workspaces/{ws}/skill-imports", files={"archive": ("skills.zip", _zip(entries))})
    assert staged.status_code == 200, staged.text
    preview = staged.json()
    for item in preview["skills"]:
        assert not any(".DS_Store" in one["path"] or "__MACOSX" in one["path"] for one in item["files"])

    committed = client.post(
        f"/api/workspaces/{ws}/skill-imports/{preview['import_id']}",
        json={"choices": [{"name": one["name"], "enable": True} for one in preview["skills"]]},
    )
    assert committed.status_code == 200, committed.text
    listed = {one["ref"]: one for one in client.get(f"/api/workspaces/{ws}/skills").json()}
    assert listed["authenticity-video-director"]["title"] == "Authenticity Video Director"
    assert listed["minimax-h3-video-prompt"]["problem"] == ""

    with SessionLocal() as db:
        skill = catalog.find(db, ws, "minimax-h3-video-prompt")
        assert skill is not None
        #: 没改名的导入一个字节都不动。
        assert (skill.root / "SKILL.md").read_bytes() == (SAMPLES / STORYBOARD / "SKILL.md").read_bytes()
        used = runtime.use_skill(db, ws, "minimax-h3-video-prompt")
        assert {"references/h3-schema.md", "agents/openai.yaml"} <= {one["path"] for one in used["files"]}
        read = runtime.read_skill_file(db, ws, "minimax-h3-video-prompt", "references/h3-schema.md")
        assert read["content"] == (SAMPLES / STORYBOARD / "references" / "h3-schema.md").read_text(encoding="utf-8")[:20000]
        #: 系统提示里的目录带上了显示名。
        assert "authenticity-video-director(Authenticity Video Director)" in runtime.skills_prompt(db, ws)


def test_SKILL_md自己写了显示名就不用openai_yaml的() -> None:
    client = fresh_client()
    ws = _workspace(client)
    entries = {
        "x/SKILL.md": b'---\nname: titled\ndescription: d\nmetadata:\n  mosael-title: "Own Title"\n---\nbody\n',
        "x/agents/openai.yaml": b'interface:\n  display_name: "Other"\n',
        "y/SKILL.md": b"---\nname: broken-yaml\ndescription: d\n---\nbody\n",
        "y/agents/openai.yaml": b"interface: &anchor\n  display_name: *anchor\n",
    }
    preview = client.post(f"/api/workspaces/{ws}/skill-imports", files={"archive": ("x.zip", _zip(entries))}).json()
    titles = {one["name"]: one["title"] for one in preview["skills"]}
    assert titles == {"titled": "Own Title", "broken-yaml": ""}, "openai.yaml 写坏了不影响导入,只是没有显示名"


# ---------------------------------------------------------------- 对话里附上压缩包 / 文件夹


def test_对话附上技能压缩包_放进导入暂存_什么都没装_确认后才装() -> None:
    client = fresh_client()
    ws = _workspace(client)
    entries = _sample_files(DIRECTOR, prefix="pack/")
    response = client.post(f"/api/workspaces/{ws}/agent-bundles", files={"archive": ("pack.zip", _zip(entries))})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assets"] == [] and body["skipped"] == []
    staged = body["skill_import"]
    assert [one["name"] for one in staged["skills"]] == ["authenticity-video-director"]
    assert "authenticity-video-director" not in {one["ref"] for one in client.get(f"/api/workspaces/{ws}/skills").json()}

    committed = client.post(f"/api/workspaces/{ws}/skill-imports/{staged['import_id']}",
                            json={"choices": [{"name": "authenticity-video-director"}]})
    assert committed.status_code == 200, committed.text
    assert "authenticity-video-director" in {one["ref"] for one in client.get(f"/api/workspaces/{ws}/skills").json()}


def test_对话附上文件夹_里面有技能也走导入暂存() -> None:
    client = fresh_client()
    ws = _workspace(client)
    response = _upload_folder(client, f"/api/workspaces/{ws}/agent-bundles", _sample_files(DIRECTOR, STORYBOARD, prefix="skills/"))
    assert response.status_code == 200, response.text
    assert len(response.json()["skill_import"]["skills"]) == 2


def test_对话附上普通压缩包_文本合订成一份文档_图片进素材库_其余逐个列出() -> None:
    client = fresh_client()
    ws = _workspace(client)
    entries = {
        "资料 包/README.md": "# 说明\n\n```bash\nmake\n```\n".encode(),
        "资料 包/src/main.py": b"print('hi')\n",
        "资料 包/config.json": b'{"a": 1}\n',
        "资料 包/图/封面.png": _png(),
        "资料 包/tool.exe": b"MZ\x00\x00\x01\x02",
        "资料 包/huge.log": b"x" * (2 * 1024 * 1024 + 1),
        "资料 包/.DS_Store": b"\x00",
        "__MACOSX/资料 包/._README.md": b"\x00\x05",
    }
    response = client.post(f"/api/workspaces/{ws}/agent-bundles", files={"archive": ("资料 包.zip", _zip(entries))})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["skill_import"] is None
    assert {(one["path"], one["reason"]) for one in body["skipped"]} == {
        ("资料 包/tool.exe", "unsupported"),
        ("资料 包/huge.log", "too_large"),
    }
    kinds = {one["kind"]: one for one in body["assets"]}
    assert set(kinds) == {"image", "document"}
    assert kinds["document"]["name"] == "资料 包.md"

    with SessionLocal() as db:
        document = db.get(Asset, kinds["document"]["id"])
        assert document is not None
        from app.media.paths import resolve_key

        text = resolve_key(document.file_key).read_text(encoding="utf-8")
    assert "## 资料 包/src/main.py" in text and "print('hi')" in text
    #: Markdown 里自带的 ``` 不会把合订本截断:外面的围栏更长。
    assert "````markdown\n# 说明" in text
    assert "资料 包/tool.exe(不是文本也不是图片)" in text
    assert "## 资料 包/图/封面.png" not in text, "图片单独进素材库,不进合订本"


@pytest.mark.parametrize(
    ("entries", "symlinks"),
    [({"../evil.txt": b"x"}, ()), ({"a.txt": b"x"}, ("link",))],
)
def test_对话附上的压缩包_路径穿越和符号链接当场拒(entries: dict[str, bytes], symlinks: tuple[str, ...]) -> None:
    client = fresh_client()
    ws = _workspace(client)
    response = client.post(f"/api/workspaces/{ws}/agent-bundles", files={"archive": ("x.zip", _zip(entries, symlinks))})
    assert response.status_code == 422 and response.json()["detail"]
    with SessionLocal() as db:
        assert db.query(Asset).filter(Asset.workspace_id == ws).count() == 0


def test_对话附上的压缩包_解开后太大当场拒() -> None:
    client = fresh_client()
    ws = _workspace(client)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bomb.txt", b"\x00" * (21 * 1024 * 1024))
    response = client.post(f"/api/workspaces/{ws}/agent-bundles", files={"archive": ("bomb.zip", buffer.getvalue())})
    assert response.status_code == 422
    assert "MB" in response.json()["detail"]


def test_对话附上普通文件夹_中文路径照收() -> None:
    client = fresh_client()
    ws = _workspace(client)
    files = {"笔记 🎬/第一场.txt": "内景 夜\n".encode(), "笔记 🎬/镜头表.csv": b"1,wide\n"}
    response = _upload_folder(client, f"/api/workspaces/{ws}/agent-bundles", files)
    assert response.status_code == 200, response.text
    [document] = response.json()["assets"]
    assert document["kind"] == "document" and document["name"] == "笔记 🎬.md"
