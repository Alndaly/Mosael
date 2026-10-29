"""手机号规范化:对外接受常见写法,库里统一 E.164。"""

from __future__ import annotations

import re

_PHONE = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw: str) -> str:
    """`13800138000` / `+8613800138000` / `8613800138000` → `+8613800138000`。

    只做确定性的空格/横线清理和 +86 补全;不猜其他国家的本地号段。
    其余号码必须显式带 `+` 国家码,避免把不同国家的本地号误当同一人。
    """
    compact = re.sub(r"[\s\-()]", "", raw.strip())
    if compact.startswith("00"):
        compact = "+" + compact[2:]
    if compact.isdigit() and len(compact) == 11:
        compact = "+86" + compact
    elif compact.isdigit() and len(compact) == 13 and compact.startswith("86"):
        compact = "+" + compact
    if not _PHONE.fullmatch(compact):
        raise ValueError("phone must be E.164 or a Chinese mobile number")
    return compact


def mask_phone(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 8 else "***"
