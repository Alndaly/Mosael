"""资产分享包(`schema: "mosael.asset/1"`)的校验。见 ADR 0027 §4「分享到社区」。

一个分享包是**一个资产能公开的那部分**:人物、场景或道具的名字、描述、提示词描述、标签,种类的专有字段里
可以公开的那几项,参考图(只以内容哈希引用,文件走社区的三步上传)与封面,以及变体(同样的形状,嵌在母体里,
只一层)。桌面端做它、社区服务收它、别人的桌面端导入它 —— 三处过的是这同一份规则。

```jsonc
{
  "schema": "mosael.asset/1",
  "kind": "character",                       // character / location / prop
  "name": "张三", "description": "…", "prompt": "…", "tags": ["主角"],
  "attributes": {"real_person": false, "blockout_color": "#aabbcc"},
  "references": [{"sha256": "…", "content_type": "image/png", "width": 1024, "height": 1024, "role": "front"}],
  "cover_sha256": "…",
  "variants": [{"name": "冬装", "description": "", "prompt": "…", "tags": [], "attributes": {},
                "references": [ … ], "cover_sha256": "…"}]
}
```

**公开的专有字段只有这几项**:人物的 `blockout_color`(白模里的人偶颜色)与 `real_person`(真人还是虚构),
场景的 `time_of_day`。**永远不带**的东西(ADR 0027 §4):音色 id 与音色样本、授权声明的原文和声明人、
关联的 3D 场景与 3D 模型、本机的任何 id —— 这些键出现在包里**任何一层**都拒,而且单独说是哪一个键,
不混在「不认识的键」里:它们不是拼错了,是不该出门。

真人人物的授权声明(「这是我本人」/「已取得本人同意公开」)**不在包里**:它是提交这一次的一个字段
(`consent_kind`),由 `check_consent` 判。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from mosael_formats.i18n import FormatError

SCHEMA = "mosael.asset/1"

#: 三种资产。和桌面端 domain/entities/catalog.KINDS 同一组。
KINDS: tuple[str, ...] = ("character", "location", "prop")

#: 参考图的角度 / 用途。和桌面端 domain/entities/catalog.ROLES 同一组、同一个顺序。
ROLES: tuple[str, ...] = (
    "front",
    "side",
    "back",
    "turnaround",
    "closeup",
    "full_body",
    "expression",
    "concept",
    "detail",
)

#: 真人人物提交时的授权声明:本人,或已取得本人同意公开。
CONSENT_KINDS: tuple[str, ...] = ("self", "authorized")

#: 参考图只收图片(一段转身视频在本机可以是参考,但分享包里只带图)。
IMAGE_TYPES: tuple[str, ...] = ("image/png", "image/jpeg", "image/webp", "image/gif", "image/avif")

#: 各种资产能公开的专有字段。
PUBLIC_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "character": ("real_person", "blockout_color"),
    "location": ("time_of_day",),
    "prop": (),
}
#: 变体的专有字段:真人与否是**这个人**的事,跟着母体,变体上不另说。
VARIANT_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "character": ("blockout_color",),
    "location": ("time_of_day",),
    "prop": (),
}

#: 在包里任何一层出现都拒的键。音色、授权声明的原文与声明人、关联的 3D 场景 / 模型、本机 id。
FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "voice_id",
        "voice",
        "voice_sample",
        "voice_samples",
        "consent",
        "consent_text",
        "declared_by",
        "declared_at",
        "scene_id",
        "model_asset_id",
        "id",
        "entity_id",
        "asset_id",
        "parent_id",
        "workspace_id",
        "cover_asset_id",
        "file_key",
        "path",
    }
)

TOP_LEVEL_KEYS = frozenset(
    {"schema", "kind", "name", "description", "prompt", "tags", "attributes", "references", "cover_sha256", "variants"}
)
VARIANT_KEYS = frozenset({"name", "description", "prompt", "tags", "attributes", "references", "cover_sha256"})
REFERENCE_KEYS = frozenset({"sha256", "content_type", "width", "height", "role"})
REQUIRED_REFERENCE_KEYS = frozenset({"sha256", "content_type", "role"})

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COLOR_RE = re.compile(r"^#[0-9a-f]{6}$")

MAX_NAME_CHARS = 160
MAX_TEXT_CHARS = 8000
MAX_TIME_OF_DAY_CHARS = 200
MAX_TAGS = 20
MAX_TAG_CHARS = 40
#: 和桌面端一个资产最多挂的参考图张数一致。
MAX_REFERENCES = 60
MAX_VARIANTS = 30
MAX_DIMENSION = 100_000
#: 嵌套深度的上限(扫禁用键时):包是一个资产,不是任意 JSON。
MAX_DEPTH = 8


class AssetBundleError(FormatError):
    """分享包不合格式。"""


@dataclass(frozen=True)
class AssetBundleSummary:
    kind: str
    name: str
    real_person: bool
    #: 引用到的全部文件哈希(母体和变体的参考图)。
    hashes: frozenset[str]
    reference_count: int
    variant_count: int
    cover_sha256: str


def _fail(where: str, detail: str) -> AssetBundleError:
    return AssetBundleError("assetBundleErr_invalid", where=where, detail=detail)


def _scan_forbidden(value: Any, where: str, depth: int = 0) -> None:
    """包里任何一层出现禁用键就拒,说出是哪一个、在哪里。"""
    if depth > MAX_DEPTH:
        raise _fail(where, "too deep")
    if isinstance(value, dict):
        for key, one in value.items():
            if isinstance(key, str) and key in FORBIDDEN_KEYS:
                raise AssetBundleError("assetBundleErr_forbiddenKey", field=key, where=where)
            _scan_forbidden(one, f"{where}.{key}", depth + 1)
    elif isinstance(value, list):
        for index, one in enumerate(value):
            _scan_forbidden(one, f"{where}[{index}]", depth + 1)


def _text(value: Any, where: str, limit: int, *, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise _fail(where, "must be a string")
    if required and not value.strip():
        raise _fail(where, "must not be empty")
    if len(value) > limit:
        raise _fail(where, f"longer than {limit} characters")
    return value


def _tags(value: Any, where: str) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        raise _fail(where, "must be a list")
    if len(value) > MAX_TAGS:
        raise _fail(where, f"more than {MAX_TAGS} tags")
    for index, tag in enumerate(value):
        _text(tag, f"{where}[{index}]", MAX_TAG_CHARS, required=True)


def _dimension(value: Any, where: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or not (0 < value <= MAX_DIMENSION):
        raise _fail(where, "must be a positive integer")


def _attributes(value: Any, where: str, allowed: tuple[str, ...]) -> bool:
    """专有字段;回 `real_person`。"""
    if value is None:
        return False
    if not isinstance(value, dict):
        raise _fail(where, "must be an object")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise _fail(where, "unknown keys: " + ", ".join(map(str, unknown)))
    real = value.get("real_person", False)
    if not isinstance(real, bool):
        raise _fail(f"{where}.real_person", "must be true or false")
    color = value.get("blockout_color")
    if color is not None and (not isinstance(color, str) or not _COLOR_RE.match(color)):
        raise _fail(f"{where}.blockout_color", "must be a lowercase #rrggbb color")
    if "time_of_day" in value:
        _text(value["time_of_day"], f"{where}.time_of_day", MAX_TIME_OF_DAY_CHARS)
    return real


def _references(value: Any, where: str, hashes: set[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise _fail(where, "must be a list")
    if len(value) > MAX_REFERENCES:
        raise _fail(where, f"more than {MAX_REFERENCES} references")
    seen: list[str] = []
    for index, ref in enumerate(value):
        here = f"{where}[{index}]"
        if not isinstance(ref, dict):
            raise _fail(here, "must be an object")
        missing = sorted(REQUIRED_REFERENCE_KEYS - set(ref))
        if missing:
            raise _fail(here, "missing: " + ", ".join(missing))
        unknown = sorted(set(ref) - REFERENCE_KEYS)
        if unknown:
            raise _fail(here, "unknown keys: " + ", ".join(map(str, unknown)))
        digest = ref["sha256"]
        if not isinstance(digest, str) or not SHA256_RE.match(digest):
            raise _fail(f"{here}.sha256", "must be a lowercase hex sha256")
        if digest in seen:
            raise _fail(f"{here}.sha256", "the same image appears twice")
        if ref["content_type"] not in IMAGE_TYPES:
            raise _fail(f"{here}.content_type", "must be one of " + ", ".join(IMAGE_TYPES))
        if ref["role"] not in ROLES:
            raise _fail(f"{here}.role", "must be one of " + ", ".join(ROLES))
        _dimension(ref.get("width"), f"{here}.width")
        _dimension(ref.get("height"), f"{here}.height")
        seen.append(digest)
        hashes.add(digest)
    return seen


def _cover(value: Any, where: str, references: list[str]) -> str:
    if value in (None, ""):
        if references:
            raise _fail(where, "must name one of the references")
        return ""
    if not isinstance(value, str) or value not in references:
        raise _fail(where, "must name one of the references")
    return value


def validate_bundle(bundle: Any) -> AssetBundleSummary:
    """校验一个分享包,返回它引用了哪些文件。不合格式抛 AssetBundleError。"""
    if not isinstance(bundle, dict):
        raise _fail("bundle", "must be an object")
    _scan_forbidden(bundle, "bundle")
    extra = set(bundle) - TOP_LEVEL_KEYS
    if extra:
        raise _fail("bundle", "unknown keys: " + ", ".join(sorted(map(str, extra))))
    if bundle.get("schema") != SCHEMA:
        raise _fail("schema", f"must be {SCHEMA}")
    kind = bundle.get("kind")
    if kind not in KINDS:
        raise _fail("kind", "must be one of " + ", ".join(KINDS))
    name = _text(bundle.get("name"), "name", MAX_NAME_CHARS, required=True)
    _text(bundle.get("description"), "description", MAX_TEXT_CHARS)
    _text(bundle.get("prompt"), "prompt", MAX_TEXT_CHARS)
    _tags(bundle.get("tags"), "tags")
    real_person = _attributes(bundle.get("attributes"), "attributes", PUBLIC_ATTRIBUTES[kind])

    hashes: set[str] = set()
    references = _references(bundle.get("references"), "references", hashes)
    if not references:
        raise _fail("references", "at least one reference image is required")
    cover = _cover(bundle.get("cover_sha256"), "cover_sha256", references)

    variants = bundle.get("variants")
    if variants is None:
        variants = []
    if not isinstance(variants, list):
        raise _fail("variants", "must be a list")
    if len(variants) > MAX_VARIANTS:
        raise _fail("variants", f"more than {MAX_VARIANTS} variants")
    reference_count = len(references)
    for index, variant in enumerate(variants):
        where = f"variants[{index}]"
        if not isinstance(variant, dict):
            raise _fail(where, "must be an object")
        unknown = sorted(set(variant) - VARIANT_KEYS)
        if unknown:
            # 变体下面不再挂变体,也不另说种类(跟着母体)。
            raise _fail(where, "unknown keys: " + ", ".join(map(str, unknown)))
        _text(variant.get("name"), f"{where}.name", MAX_NAME_CHARS, required=True)
        _text(variant.get("description"), f"{where}.description", MAX_TEXT_CHARS)
        _text(variant.get("prompt"), f"{where}.prompt", MAX_TEXT_CHARS)
        _tags(variant.get("tags"), f"{where}.tags")
        _attributes(variant.get("attributes"), f"{where}.attributes", VARIANT_ATTRIBUTES[kind])
        refs = _references(variant.get("references"), f"{where}.references", hashes)
        _cover(variant.get("cover_sha256"), f"{where}.cover_sha256", refs)
        reference_count += len(refs)

    return AssetBundleSummary(
        kind=kind,
        name=name,
        real_person=real_person,
        hashes=frozenset(hashes),
        reference_count=reference_count,
        variant_count=len(variants),
        cover_sha256=cover,
    )


def check_consent(summary: AssetBundleSummary, consent_kind: Any) -> str:
    """提交时的授权声明。真人人物必须声明「这是我本人」或「已取得本人同意公开」;其余不该带声明。

    返回规整后的声明(虚构的是空串)。
    """
    value = consent_kind.strip() if isinstance(consent_kind, str) else consent_kind
    if summary.real_person:
        if value not in CONSENT_KINDS:
            raise AssetBundleError("assetBundleErr_consentRequired", kinds=" / ".join(CONSENT_KINDS))
        return str(value)
    if value not in (None, ""):
        raise AssetBundleError("assetBundleErr_consentNotApplicable")
    return ""


__all__ = [
    "AssetBundleError",
    "AssetBundleSummary",
    "CONSENT_KINDS",
    "FORBIDDEN_KEYS",
    "IMAGE_TYPES",
    "KINDS",
    "PUBLIC_ATTRIBUTES",
    "ROLES",
    "SCHEMA",
    "VARIANT_ATTRIBUTES",
    "check_consent",
    "validate_bundle",
]
