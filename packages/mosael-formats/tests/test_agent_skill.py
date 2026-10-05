"""SKILL.md 的读、写、校验,以及压缩包 / 插件包里的技能(ADR 0040)。"""

from __future__ import annotations

import io
import zipfile

import pytest

from mosael_formats import agent_skill as skill
from mosael_formats.agent_skill import SkillDoc, SkillError

#: 照 Anthropic 公开技能库与 Claude Code 文档里的写法拼的一份:块标量、引号、metadata、列表形式的
#: allowed-tools、规范之外的字段(Claude Code 的 `disable-model-invocation`、一个列表套映射的 `hooks`)。
REAL_WORLD = """---
name: pdf-processing
description: >-
  Extracts text and tables from PDF files, fills PDF forms, and merges multiple PDFs.
  Use when working with PDF documents or when the user mentions PDFs, forms, or document extraction.
license: "Apache-2.0"   # 许可证
compatibility: 'Requires Python 3.12+ and network access'
metadata:
  author: example-org
  version: "1.0"
  mosael-title: 处理 PDF
allowed-tools:
  - Read
  - Bash(python:*)
disable-model-invocation: true
hooks:
  - matcher: "Bash"
    command: echo hi   # 注释
---

# PDF Processing

## Quick start
Use pdfplumber.
"""


def test_真实写法的头_各字段读对() -> None:
    doc = skill.parse_skill_md(REAL_WORLD)
    assert doc.name == "pdf-processing"
    assert doc.description.startswith("Extracts text and tables from PDF files, fills PDF forms, and merges multiple PDFs. Use when")
    assert "\n" not in doc.description, "> 块把换行折成空格"
    assert doc.license == "Apache-2.0" and doc.compatibility.startswith("Requires Python")
    assert doc.metadata == {"author": "example-org", "version": "1.0", "mosael-title": "处理 PDF"}
    assert doc.title == "处理 PDF"
    assert doc.allowed_tools == "Read Bash(python:*)"
    assert set(doc.extra) == {"disable-model-invocation", "hooks"}
    assert doc.extra["hooks"].startswith("hooks:\n  - matcher:") and "# 注释" in doc.extra["hooks"], "不认识的字段留原文"
    assert doc.body.startswith("# PDF Processing")


def test_写回再读_同一个值_不认识的字段一字不改() -> None:
    doc = skill.parse_skill_md(REAL_WORLD).with_title("PDF 处理")
    text = skill.render_skill_md(doc)
    again = skill.parse_skill_md(text)
    assert again == doc
    assert "disable-model-invocation: true\n" in text
    assert "  - Bash(python:*)" in text, "allowed-tools 原文放回(Mosael 不编辑它)"


@pytest.mark.parametrize(
    "value",
    ["普通", 'a "quoted" \\ back', "多行\n第二行", "tab\there", "ctrl\x01x", "  leading and trailing  ", "# not a comment",
     "key: value", "", "emoji 🎬", "line sep\u2028x"],
)
def test_任何字符串写进去读出来不变(value: str) -> None:
    doc = SkillDoc(name="a", description="d", metadata={"k": value} if value else {}, license=value.strip())
    assert skill.parse_skill_md(skill.render_skill_md(doc)) == doc


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        ("name: a\ndescription: |\n  line one\n  line two\n", "line one\nline two\n"),
        ("name: a\ndescription: |-\n  keep\n\n  gap\n", "keep\n\ngap"),
        ("name: a\ndescription: >\n  folded\n  text\n\n  next\n", "folded text\nnext\n"),
        ("name: a\ndescription: plain that\n  continues here\n", "plain that continues here"),
        ('name: a\ndescription: "double \\u4e2d \\"q\\"\n  next line"\n', 'double 中 "q" next line'),
        ("name: a\ndescription: 'it''s single'\n", "it's single"),
        ("name: a\ndescription: x # comment\n", "x"),
        ("name: a\ndescription: \"x\" # comment\n", "x"),
    ],
)
def test_标量的几种写法(head: str, expected: str) -> None:
    data, _ = skill.load_frontmatter(head)
    assert data["description"] == expected


def test_流式列表与映射() -> None:
    data, _ = skill.load_frontmatter('name: a\ntools: [Read, "Grep x", \'y\']\nm: {a: 1, b: "two"}\n')
    assert data["tools"] == ["Read", "Grep x", "y"]
    assert data["m"] == {"a": "1", "b": "two"}


@pytest.mark.parametrize(
    ("head", "key"),
    [
        ("name: &a x\n", "skillErr_yamlUnsupported"),
        ("name: *a\n", "skillErr_yamlUnsupported"),
        ("name: !!str x\n", "skillErr_yamlUnsupported"),
        ("name: a\nname: b\n", "skillErr_yamlDuplicateKey"),
        ('name: "unterminated\n', "skillErr_yamlUnterminated"),
        ("name: a\n\tdescription: b\n", "skillErr_yamlTab"),
        ("name: a\n  description: b\n", "skillErr_yamlIndent"),
        ("just text\n", "skillErr_yamlSyntax"),
    ],
)
def test_不认的YAML说清是哪一行(head: str, key: str) -> None:
    with pytest.raises(SkillError) as caught:
        skill.load_frontmatter(head)
    assert caught.value.key == key


def test_YAML炸弹进不来() -> None:
    bomb = "name: a\nx: &a [1, 1]\ny: &b [*a, *a]\nz: [*b, *b]\n"
    with pytest.raises(SkillError) as caught:
        skill.load_frontmatter(bomb)
    assert caught.value.key == "skillErr_yamlUnsupported"


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("# no header\n", "skillErr_noFrontmatter"),
        ("---\nname: a\n", "skillErr_frontmatterUnclosed"),
        ("---\nname: a\n---\n", "skillErr_missingField"),
        ("---\ndescription: d\n---\n", "skillErr_missingField"),
        ("---\nname: PDF-Processing\ndescription: d\n---\n", "skillErr_badName"),
        ("---\nname: -pdf\ndescription: d\n---\n", "skillErr_badName"),
        ("---\nname: pdf--x\ndescription: d\n---\n", "skillErr_badName"),
        ("---\nname: 带货\ndescription: d\n---\n", "skillErr_badName"),
        (f"---\nname: {'a' * 65}\ndescription: d\n---\n", "skillErr_badName"),
        (f"---\nname: a\ndescription: {'d' * 1025}\n---\n", "skillErr_tooLong"),
        (f"---\nname: a\ndescription: d\ncompatibility: {'c' * 501}\n---\n", "skillErr_tooLong"),
        ("---\nname: a\ndescription: d\nmetadata:\n  k:\n    nested: x\n---\n", "skillErr_metadataNotStrings"),
        ("---\nname: a\ndescription: [x]\n---\n", "skillErr_fieldNotText"),
        (f"---\nname: a\ndescription: d\n---\n{'x' * (64 * 1024)}", "skillErr_skillMdTooLarge"),
    ],
)
def test_规范的规矩(text: str, key: str) -> None:
    with pytest.raises(SkillError) as caught:
        skill.parse_skill_md(text)
    assert caught.value.key == key


def test_文件夹名要和name一致_只在给了文件夹时查() -> None:
    text = "---\nname: a\ndescription: d\n---\n"
    assert skill.parse_skill_md(text).name == "a"
    with pytest.raises(SkillError) as caught:
        skill.parse_skill_md(text, folder="b")
    assert caught.value.key == "skillErr_folderMismatch"


def test_CRLF与BOM() -> None:
    doc = skill.parse_skill_md("\ufeff---\r\nname: a\r\ndescription: d\r\n---\r\n\r\nbody\r\n")
    assert (doc.name, doc.description, doc.body) == ("a", "d", "body\n")


@pytest.mark.parametrize("path", ["../x", "a/../../x", "/etc/passwd", "C:/x", "a\\b", "", ".", "a/" * 9 + "x", "x\x00y"])
def test_越界与古怪的路径一律拒(path: str) -> None:
    with pytest.raises(SkillError) as caught:
        skill.check_path(path)
    assert caught.value.key == "skillErr_badPath"


def test_路径规整() -> None:
    assert skill.check_path("./references//a.md") == "references/a.md"


def _zip(entries: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = 0o120777 << 16
            archive.writestr(info, "/etc/passwd")
    return buffer.getvalue()


SIMPLE = b"---\nname: short-video-ads\ndescription: make ads\n---\n\nsteps\n"


def test_压缩包_外面套一层_垃圾丢掉_一个技能() -> None:
    data = _zip({
        "repo-main/SKILL.md": SIMPLE,
        "repo-main/references/a.md": b"ref",
        "repo-main/scripts/run.py": b"print(1)",
        "__MACOSX/repo-main/._SKILL.md": b"junk",
        "repo-main/.DS_Store": b"junk",
    })
    [bundle] = skill.read_skill_archive(data)
    assert bundle.doc.name == "short-video-ads" and bundle.folder == "repo-main"
    assert set(bundle.files) == {"SKILL.md", "references/a.md", "scripts/run.py"}


def test_压缩包里几个技能_嵌在别的技能里的SKILL不另算() -> None:
    other = b"---\nname: brand-rules\ndescription: rules\n---\n"
    nested = b"---\nname: inner\ndescription: x\n---\n"
    data = _zip({"a/SKILL.md": SIMPLE, "a/examples/SKILL.md": nested, "b/SKILL.md": other, "README.md": b"x"})
    bundles = skill.read_skill_archive(data)
    assert [one.doc.name for one in bundles] == ["short-video-ads", "brand-rules"]
    assert "examples/SKILL.md" in bundles[0].files


@pytest.mark.parametrize(
    ("entries", "symlink", "key"),
    [
        ({"SKILL.md": SIMPLE}, "link", "skillErr_symlink"),
        ({"../SKILL.md": SIMPLE}, None, "skillErr_badPath"),
        ({"x/readme.md": b"x"}, None, "skillErr_noSkillMd"),
        ({"a/SKILL.md": SIMPLE, "b/SKILL.md": SIMPLE}, None, "skillErr_duplicateName"),
        ({"SKILL.md": b"\xff\xfe"}, None, "skillErr_notUtf8"),
    ],
)
def test_压缩包不合格(entries: dict[str, bytes], symlink: str | None, key: str) -> None:
    with pytest.raises(SkillError) as caught:
        skill.read_skill_archive(_zip(entries, symlink=symlink))
    assert caught.value.key == key


def test_不是zip() -> None:
    with pytest.raises(SkillError) as caught:
        skill.read_skill_archive(b"not a zip")
    assert caught.value.key == "skillErr_notZip"


def test_解压炸弹按声明的大小在解之前就拒() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("SKILL.md", SIMPLE)
        archive.writestr("big.bin", b"\0" * (skill.MAX_ARCHIVE_UNPACKED_BYTES + 1))
    with pytest.raises(SkillError) as caught:
        skill.read_skill_archive(buffer.getvalue())
    assert caught.value.key == "skillErr_archiveTooLarge"


def test_单个文件和整个技能的上限() -> None:
    with pytest.raises(SkillError) as caught:
        skill.check_files({"SKILL.md": 10, "a.bin": skill.MAX_FILE_BYTES + 1})
    assert caught.value.key == "skillErr_fileTooLarge"
    with pytest.raises(SkillError) as caught:
        skill.check_files({"SKILL.md": 10, **{f"f{i}": 1 for i in range(skill.MAX_SKILL_FILES)}})
    assert caught.value.key == "skillErr_tooManyFiles"
    with pytest.raises(SkillError) as caught:
        skill.check_files({"SKILL.md": 10, **{f"f{i}": skill.MAX_FILE_BYTES for i in range(6)}})
    assert caught.value.key == "skillErr_skillTooLarge"


def test_导出的压缩包能原样导回来() -> None:
    files = {"SKILL.md": SIMPLE, "references/卖点.md": "模板".encode(), "assets/end.png": b"\x89PNG\x00"}
    [bundle] = skill.read_skill_archive(skill.write_skill_archive([("short-video-ads", files)]))
    assert bundle.files == files and bundle.folder == "short-video-ads"


def test_插件包里的技能_目录名就是name_不许有散落的文件() -> None:
    files = {"mosael.plugin.json": b"{}", "skills/tips/SKILL.md": b"---\nname: tips\ndescription: t\n---\n",
             "skills/tips/a.md": b"x"}
    [bundle] = skill.plugin_skill_files(files)
    assert bundle.doc.name == "tips" and set(bundle.files) == {"SKILL.md", "a.md"}
    assert skill.plugin_skill_files({"mosael.plugin.json": b"{}"}) == []
    with pytest.raises(SkillError) as caught:
        skill.plugin_skill_files({"skills/other/SKILL.md": b"---\nname: tips\ndescription: t\n---\n"})
    assert caught.value.key == "skillErr_folderMismatch"
    with pytest.raises(SkillError) as caught:
        skill.plugin_skill_files({"skills/README.md": b"x"})
    assert caught.value.key == "skillErr_pluginStrayFile"
    with pytest.raises(SkillError) as caught:
        skill.plugin_skill_files({"skills/x/notes.md": b"x"})
    assert caught.value.key == "skillErr_noSkillMd"


def test_按内容判文本() -> None:
    assert skill.is_text("中文".encode())
    assert not skill.is_text(b"\x89PNG\x00\x01")
    assert not skill.is_text(b"\xff\xfe\xfd")
