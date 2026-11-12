"""生成任务输入的边界。

`input` 是从客户端直接来的 JSON；适配器会把它原样交给上游。这里不是“尽量帮用户填默认值”，
而是**只允许已知的键、给每个键定上界**：一个没有上界的 `n` 或 `duration` 会变成“按一份预占
消耗 N 倍上游资源”的账单漏洞（见 ADR 0100 的定价/预占契约）。
"""

from __future__ import annotations

from collections.abc import Mapping

from cloud.errors import CloudError

MAX_PROMPT_CHARS = 20_000
MAX_NEGATIVE_CHARS = 20_000
MAX_IMAGES = 8
MAX_DURATION_SECONDS = 60
MAX_URL_CHARS = 2_048
MAX_REFERENCE_IMAGES = 8

_STRING_KEYS = {
    "prompt": MAX_PROMPT_CHARS,
    "negative_prompt": MAX_NEGATIVE_CHARS,
    "size": 64,
    "quality": 64,
    "background": 64,
    "output_format": 64,
    "resolution": 64,
    "aspect_ratio": 64,
}
_INT_KEYS = {"n", "num_images", "duration_seconds"}
_URL_KEYS = {"first_frame", "last_frame", "image", "reference_image"}
_BOOL_KEYS = {"generate_audio"}
_KEYS = set(_STRING_KEYS) | _INT_KEYS | _URL_KEYS | _BOOL_KEYS | {"reference_images"}


def _bad(field: str) -> CloudError:
    return CloudError(400, "invalid_request", field=field)


def _url(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _bad(field)
    text = value.strip()
    if len(text) > MAX_URL_CHARS:
        raise _bad(field)
    if not text.startswith(("https://", "http://", "data:")):
        raise _bad(field)
    return text


def _int(value: object, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise _bad(field)
    number = int(value)
    if not minimum <= number <= maximum:
        raise _bad(field)
    return number


def normalize_job_input(raw: Mapping[str, object] | None) -> dict[str, object]:
    """校验并返回只含允许键的输入；未知键直接拒绝，避免适配器以后误读意料外的字段。"""
    if not isinstance(raw, Mapping):
        raise _bad("input")
    unknown = sorted(str(key) for key in raw if str(key) not in _KEYS)
    if unknown:
        raise _bad(unknown[0])
    data: dict[str, object] = {}
    for key in _STRING_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if not isinstance(value, str):
            raise _bad(key)
        text = value.strip()
        if key == "prompt" and not text:
            raise _bad(key)
        if len(text) > _STRING_KEYS[key]:
            raise _bad(key)
        data[key] = text
    if "prompt" not in data:
        raise _bad("prompt")
    for key in _URL_KEYS:
        if key in raw:
            data[key] = _url(raw[key], key)
    for key in _INT_KEYS:
        if key not in raw:
            continue
        maximum = MAX_IMAGES if key in {"n", "num_images"} else MAX_DURATION_SECONDS
        data[key] = _int(raw[key], key, minimum=1, maximum=maximum)
    if "n" in data and "num_images" in data and data["n"] != data["num_images"]:
        raise _bad("num_images")
    if "n" not in data and "num_images" in data:
        data["n"] = data["num_images"]
    for key in _BOOL_KEYS:
        if key in raw:
            if not isinstance(raw[key], bool):
                raise _bad(key)
            data[key] = raw[key]
    if "reference_images" in raw:
        value = raw["reference_images"]
        if not isinstance(value, list) or len(value) > MAX_REFERENCE_IMAGES:
            raise _bad("reference_images")
        data["reference_images"] = [_url(one, "reference_images") for one in value]
    return data


def estimated_units(reservation: Mapping[str, object], data: Mapping[str, object]) -> dict[str, int]:
    """预占按**这次输入**算，而不是只按模型目录里的静态最小值。

    `n` 和 `duration_seconds` 是用户可控的；如果预占仍是 1 张 / 5 秒，结算的
    `min(actual, reserved)` 会把一次 50 张的请求截成 1 张的价格。
    """
    units: dict[str, int] = {}
    for key, value in reservation.items():
        try:
            units[str(key)] = max(1, int(value))
        except (TypeError, ValueError):
            raise _bad(str(key)) from None
    if "image" in units:
        units["image"] = max(units["image"], int(data.get("n") or data.get("num_images") or 1))
    if "second" in units:
        units["second"] = max(units["second"], int(data.get("duration_seconds") or 1))
    return units
