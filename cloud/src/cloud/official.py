"""官方内容 = **官方账号发布的分享**。

维护者裁决:插件和工作流本身就是分享,官方插件 / 官方工作流就是官方账号发布的分享。
所以这里没有第二套表、没有第二套 payload:

- 官方账号是 `cloud_users` 里 `official = true` 的那一行;
- 官方分享就是同一张 `cloud_shares` 里的普通行,`kind` 用 `plugin` / `workflow`,
  `owner_user_id` 指向官方账号。

**只有这个模块会写 `official = true`。** 注册接口与 `PUT /me` 都不认识这个字段(测试钉住)。

官方账号为什么登不上(三条一起保证,不靠"没人知道密码"):

1. 种子**不设密码**(`password_hash = NULL`),密码登录走 `verify_password` 那条路永远失败;
2. 邮箱是 RFC 2606 保留的 `.example` 顶级域(`official@mosael.example`),DNS 保证解析不到,
   验证码邮件**不可能被任何人收到**;登录发码对官方账号还会直接**不投递**(见
   `email_codes.issue_code`,与未知邮箱同一句响应,不给探测口);
3. `api.auth.open_session` 是**所有**登录路径的唯一发会话入口,它对 `official` 账号直接拒绝 ——
   即使将来多一条登录方式、或者有人拿到了某个码,也换不到会话。

种子命令: `python -m cloud.cli seed-official --bundle <path.json>`

幂等键用 bundle 里的稳定 `slug`(`cloud_shares.slug`),**不用标题**:

- 标题是给人改的 —— 运营改一次标题,按标题去重就会在下一次部署产出第二条;
- slug 是发布方的稳定标识,Git 里的 bundle 改了标题也不会变;
- 唯一索引 `(owner_user_id, kind, slug)` 让并发 / 重复执行在数据库层也最多一行。

**只补缺,不覆盖**:已存在的行(按 owner + kind + slug)整行跳过,标题 / 简介 / payload /
许可都不动;用户自己的分享没有 slug,永远不会被种子碰到。
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloud.db import Database
from cloud.domain.shares import (
    HUMAN_PAYLOAD_LIMIT,
    MAX_LICENSE,
    MAX_PAYLOAD_BYTES,
    MAX_SUMMARY,
    MAX_TITLE,
    create_share,
    payload_bytes,
)
from cloud.errors import CloudError
from cloud.models import CloudShare, CloudUser

#: 固定短名。它在 `identity.RESERVED_HANDLES` 里,普通用户注册不到,所以"handle 是 mosael"
#: 就等于"这个账号是种子建的"。
OFFICIAL_HANDLE = "mosael"
OFFICIAL_DISPLAY_NAME = "Mosael 官方"
#: 固定头像种子:官方头像的颜色不随部署漂移。
OFFICIAL_AVATAR_SEED = "mosael-official"
#: RFC 2606 保留的 `.example` 顶级域:公网 DNS 永远解析不到,所以这封信没人收得到。
#: (`.invalid` 会被 Pydantic 的 EmailStr 直接判成非法地址,登录会变成 422;`.example` 让
#: 官方账号和普通账号走**同一套**接口,由发码 / 发会话那两道闸来挡。)
OFFICIAL_EMAIL = "official@mosael.example"

#: bundle 顶层键 → 分享 kind。**只认这两个**:画板不是"官方发布内容"的一部分。
BUNDLE_LISTS = {"plugins": "plugin", "workflows": "workflow"}

MAX_SLUG = 80
#: slug 是稳定标识,只允许小写字母 / 数字 / `.` `_` `-`,且以字母或数字开头。
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class SeedError(ValueError):
    """bundle 或落库出了人该看见的问题。CLI 把它变成 stderr + 退出码 2。"""


@dataclass(frozen=True)
class SeedReport:
    account_created: bool
    created: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        parts = [
            f"官方账号 @{OFFICIAL_HANDLE} "
            + ("已创建" if self.account_created else "已存在(补齐缺的字段)")
        ]
        for list_name, kind in BUNDLE_LISTS.items():
            parts.append(
                f"{list_name}: 新增 {self.created.get(kind, 0)} 条 / 已存在 {self.skipped.get(kind, 0)} 条"
            )
        return ";".join(parts)


def load_bundle(path: str | Path) -> dict[str, Any]:
    """读并整份校验 bundle。**先校验、后落库**:结构不对不会留下半个官方账号。"""
    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise SeedError(f"读不到 bundle: {source}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SeedError(f"bundle 不是合法 JSON: {exc}") from exc
    check_bundle(data)
    return data


def check_bundle(data: Any) -> None:
    if not isinstance(data, dict):
        raise SeedError("bundle 顶层必须是一个 JSON 对象")
    unknown = sorted(set(data) - set(BUNDLE_LISTS))
    if unknown:
        raise SeedError(f"bundle 顶层有不认识的键: {', '.join(unknown)}")
    for list_name in BUNDLE_LISTS:
        entries = data.get(list_name, [])
        if not isinstance(entries, list):
            raise SeedError(f"`{list_name}` 必须是数组")
        seen: set[str] = set()
        for index, entry in enumerate(entries):
            where = f"{list_name}[{index}]"
            if not isinstance(entry, dict):
                raise SeedError(f"{where} 必须是对象")
            slug = _clean_slug(entry.get("slug"), where)
            if slug in seen:
                raise SeedError(f"{where}: `{list_name}` 里 slug 重复: {slug}")
            seen.add(slug)
            title = entry.get("title")
            if not isinstance(title, str) or not title.strip():
                raise SeedError(f"{where}: `title` 必须是非空字符串")
            if len(title.strip()) > MAX_TITLE:
                raise SeedError(f"{where}: `title` 超过 {MAX_TITLE} 个字符")
            if "payload" not in entry or entry["payload"] is None:
                raise SeedError(f"{where}: `payload` 必填")
            for key, limit in (("summary", MAX_SUMMARY), ("license", MAX_LICENSE)):
                value = entry.get(key)
                if value is not None and not isinstance(value, str):
                    raise SeedError(f"{where}: `{key}` 必须是字符串或 null")
                if isinstance(value, str) and len(value.strip()) > limit:
                    raise SeedError(f"{where}: `{key}` 超过 {limit} 个字符")
            try:
                size = payload_bytes(entry["payload"])
            except CloudError as exc:
                raise SeedError(f"{where}: `payload` 必须是一份 JSON") from exc
            if size > MAX_PAYLOAD_BYTES:
                raise SeedError(f"{where}: `payload` 超过 {HUMAN_PAYLOAD_LIMIT}")
            # locale 是可选的操作者标注:分享表没有 locale 列,payload 也必须和用户分享同构,
            # 所以它**不落库、不参与去重**。多语言版本请用不同 slug。
            locale = entry.get("locale")
            if locale is not None and (not isinstance(locale, str) or not locale.strip() or len(locale) > 8):
                raise SeedError(f"{where}: `locale` 必须是 1–8 个字符的字符串或 null")


def _clean_slug(raw: Any, where: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise SeedError(f"{where}: `slug` 必填")
    value = raw.strip()
    if len(value) > MAX_SLUG or not SLUG_RE.fullmatch(value):
        raise SeedError(f"{where}: `slug` 只能用小写字母、数字和 . _ -,最长 {MAX_SLUG},且以字母或数字开头")
    return value


def seed_official(database_url: str, bundle: Mapping[str, Any]) -> SeedReport:
    """把 bundle 里的官方插件 / 工作流补进分享表。**幂等**:重复跑不新增行、不覆盖改动。"""
    check_bundle(bundle)
    database = Database(database_url)
    try:
        session = database.session()
        try:
            user, account_created = _ensure_official_user(session)
            created = {kind: 0 for kind in BUNDLE_LISTS.values()}
            skipped = {kind: 0 for kind in BUNDLE_LISTS.values()}
            for list_name, kind in BUNDLE_LISTS.items():
                for entry in bundle.get(list_name, []):
                    slug = _clean_slug(entry["slug"], list_name)
                    if _exists(session, user.id, kind, slug):
                        skipped[kind] += 1
                        continue
                    if _create(session, user, kind=kind, slug=slug, entry=entry):
                        created[kind] += 1
                    else:
                        # 唯一索引撞了:另一个进程刚刚写了同一行。当作"已存在"。
                        skipped[kind] += 1
            return SeedReport(account_created=account_created, created=created, skipped=skipped)
        finally:
            session.close()
    finally:
        database.dispose()


def _ensure_official_user(session: Session) -> tuple[CloudUser, bool]:
    """按固定 handle 找官方账号;不存在就建。**不设密码**,`official` 只在这里写 true。

    已存在时**只补空字段**(昵称 / 头像种子),不改邮箱、密码、handle,也不动它已经发的东西。
    """
    user = session.scalar(select(CloudUser).where(CloudUser.handle == OFFICIAL_HANDLE))
    if user is not None:
        changed = False
        if not user.official:
            # 这个 handle 是保留字,能落在它上面的只可能是早先的种子输出。
            user.official = True
            changed = True
        if not user.display_name:
            user.display_name = OFFICIAL_DISPLAY_NAME
            changed = True
        if not user.avatar_seed:
            user.avatar_seed = OFFICIAL_AVATAR_SEED
            changed = True
        if changed:
            session.commit()
        return user, False

    user = CloudUser(
        email=OFFICIAL_EMAIL,
        password_hash=None,
        email_verified_at=None,
        display_name=OFFICIAL_DISPLAY_NAME,
        handle=OFFICIAL_HANDLE,
        avatar_seed=OFFICIAL_AVATAR_SEED,
        official=True,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise SeedError(
            f"{OFFICIAL_EMAIL} 已经被另一个账号占用;官方账号没有建出来。"
            "先人工确认那个账号是谁,再决定是否手工处理。"
        ) from exc
    return user, True


def _exists(session: Session, owner_id: str, kind: str, slug: str) -> bool:
    return (
        session.scalar(
            select(CloudShare.id).where(
                CloudShare.owner_user_id == owner_id,
                CloudShare.kind == kind,
                CloudShare.slug == slug,
            )
        )
        is not None
    )


def _create(session: Session, user: CloudUser, *, kind: str, slug: str, entry: Mapping[str, Any]) -> bool:
    """走**和用户发布完全一样**的 `create_share`(标题 / 简介 / 2 MB 校验、同一 serializer)。

    返回 False 表示唯一索引撞上了(并发种子),不是错误。
    """
    try:
        create_share(
            session,
            user,
            kind=kind,
            title=entry["title"],
            summary=entry.get("summary"),
            payload=entry["payload"],
            license=entry.get("license"),
            slug=slug,
        )
    except IntegrityError:
        session.rollback()
        return False
    except CloudError as exc:
        session.rollback()
        raise SeedError(f"{kind} `{slug}`: {exc.code}") from exc
    return True
