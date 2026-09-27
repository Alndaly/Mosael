"""一个**假的社区服务**,照 ADR 0026 的「API 约定」实现应用用到的那几条接口。

装在 `httpx.MockTransport` 上,测试把 `domain/community/transport.make_client` 换成连它的客户端 ——
设备授权、令牌轮换(含重用判盗)、三步上传(去重)、分享的版本、工作流 / 插件的提交,全都在内存里。

它刻意**比真服务更挑剔**的几处:刷新令牌用过一次再用就吊销整个会话(不给 20 秒宽限期)—— 应用这一侧的
single-flight 必须真的只刷新一次;提交快照时每个哈希都得已经传上来过。
"""

from __future__ import annotations

import email.parser
import email.policy
import hashlib
import itertools
import json
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

ORIGIN = "https://community.test"
PREFIX = "/api/community/v1"
STORAGE = "https://storage.test"


def _error(status: int, code: str, message: str = "") -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": message or code}})


@dataclass
class Session:
    id: str
    user: dict[str, Any]
    revoked: bool = False


@dataclass
class DeviceCode:
    user_code: str
    approved: bool = False
    denied: bool = False
    expired: bool = False
    #: 接下来几次轮询先回 slow_down。
    slow_downs: int = 0


@dataclass
class Share:
    slug: str
    board_key: str
    title: str
    visibility: str
    versions: list[dict[str, Any]] = field(default_factory=list)
    withdrawn: bool = False


def parse_multipart(request: httpx.Request) -> tuple[dict[str, str], dict[str, tuple[str, bytes, str]]]:
    """multipart 请求体 → (字段, 文件)。用标准库的 email 解析器,不另装东西。"""
    raw = request.read()
    head = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(head + raw)
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes, str]] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_param("filename", header="content-disposition")
        payload = part.get_payload(decode=True) or b""
        if filename:
            files[str(name)] = (str(filename), payload, part.get_content_type())
        else:
            fields[str(name)] = payload.decode("utf-8")
    return fields, files


class FakeCommunity:
    def __init__(self, *, presigned: bool = False) -> None:
        self.lock = threading.RLock()
        self.presigned = presigned
        self.calls: list[tuple[str, str]] = []
        self.user = {"id": "u-1", "handle": "alice", "display_name": "Alice"}
        self.devices: dict[str, DeviceCode] = {}
        self.sessions: dict[str, Session] = {}
        #: 刷新令牌 → (会话 id, 用过没有)
        self.refresh_tokens: dict[str, list[Any]] = {}
        #: 访问令牌 → 会话 id
        self.access_tokens: dict[str, str] = {}
        self.refresh_delay = 0.0
        self.refresh_status: int | None = None
        #: 为真时,受保护的接口对**任何**访问令牌都回 401(续期也救不回来)。
        self.always_unauthorized = False
        #: 每次 /me 被调用时跑一下(测试用来看「用新访问令牌时,新刷新令牌已经落盘了没有」)。
        self.on_me: Any = None
        self.blobs: dict[str, bytes] = {}
        #: sha256 → 还要失败几次(回 503)
        self.put_failures: dict[str, int] = {}
        self.puts: list[str] = []
        #: 每个文件传上来之后跑一下(测试用来在传到一半时取消任务)。
        self.on_put: Any = None
        self.upload_requests: list[list[str]] = []
        self.shares: dict[str, Share] = {}
        self.workflows: dict[str, dict[str, Any]] = {}
        self.plugins: list[dict[str, Any]] = []
        self.index: list[dict[str, Any]] = []
        #: slug → {"asset_kind", "status", "versions": [{"bundle", "consent_kind"}]}
        self.assets: dict[str, dict[str, Any]] = {}
        #: 下载这些哈希时回别的内容(模拟被换过的文件)。
        self.tampered: set[str] = set()
        #: 为真时这台「社区」只是个普通网站:什么都回一张 404 网页(部署设置里填了一个没部署社区的站点)。
        self.just_a_website = False
        self._slugs = itertools.count(1)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def client(self, timeout: float = 30.0) -> httpx.Client:
        return httpx.Client(transport=self.transport, timeout=timeout, follow_redirects=True)

    # --- 测试里用来拨动它的几样 ------------------------------------------------

    def approve(self, user_code: str) -> None:
        with self.lock:
            next(one for one in self.devices.values() if one.user_code == user_code).approved = True

    def device(self, user_code: str) -> DeviceCode:
        return next(one for one in self.devices.values() if one.user_code == user_code)

    def refresh_calls(self) -> int:
        return sum(1 for method, path in self.calls if path == "/auth/refresh")

    def count(self, path: str) -> int:
        return sum(1 for _method, called in self.calls if called == path)

    def revoke_all_sessions(self) -> None:
        with self.lock:
            for session in self.sessions.values():
                session.revoked = True

    def reject_current_access_tokens(self) -> None:
        """现有的访问令牌全部作废(会话还在)—— 下一次请求会撞上 401、续一次就好。"""
        with self.lock:
            self.access_tokens.clear()

    def live_refresh_token(self) -> str:
        with self.lock:
            live = [token for token, (sid, used) in self.refresh_tokens.items() if not used and not self.sessions[sid].revoked]
            assert len(live) == 1, live
            return live[0]

    # --- 令牌 -------------------------------------------------------------------

    def _pair(self, session: Session) -> dict[str, Any]:
        access = "at-" + secrets.token_hex(8)
        refresh = "rt-" + secrets.token_hex(16)
        self.access_tokens[access] = session.id
        self.refresh_tokens[refresh] = [session.id, False]
        return {"access_token": access, "refresh_token": refresh, "expires_in": 900, "user": dict(session.user)}

    def _session_of(self, request: httpx.Request) -> Session | None:
        header = request.headers.get("authorization", "")
        if not header.startswith("Bearer ") or self.always_unauthorized:
            return None
        sid = self.access_tokens.get(header[len("Bearer "):])
        session = self.sessions.get(sid or "")
        return session if session is not None and not session.revoked else None

    # --- 路由 -------------------------------------------------------------------

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlsplit(str(request.url))
        if f"{url.scheme}://{url.netloc}" == STORAGE:
            with self.lock:
                self.calls.append((request.method, "storage:" + url.path))
            if request.method == "GET":
                return self._get_blob(url.path.rsplit("/", 1)[-1])
            return self._put_blob(request, url.path.rsplit("/", 1)[-1])
        assert f"{url.scheme}://{url.netloc}" == ORIGIN, url
        if self.just_a_website:
            return httpx.Response(404, text="<html><body>Not Found</body></html>", headers={"content-type": "text/html"})
        assert url.path.startswith(PREFIX), url.path
        path = url.path[len(PREFIX):]
        with self.lock:
            self.calls.append((request.method, path))
        method = request.method
        if path == "/auth/device/code" and method == "POST":
            return self._device_code(request)
        if path == "/auth/device/token" and method == "POST":
            return self._device_token(request)
        if path == "/auth/refresh" and method == "POST":
            return self._refresh(request)
        if path == "/plugins/index.json" and method == "GET":
            return httpx.Response(200, json={"plugins": self.index})
        if path.startswith("/assets") and method == "GET":
            return self._public_asset(request, path)
        session = self._session_of(request)
        if session is None:
            return _error(401, "unauthorized")
        if path == "/auth/logout" and method == "POST":
            session.revoked = True
            return httpx.Response(204)
        if path == "/me" and method == "GET":
            if self.on_me is not None:
                self.on_me(request)
            return httpx.Response(200, json=session.user)
        if path == "/shares/uploads" and method == "POST":
            return self._uploads(request)
        if path.startswith("/uploads/") and method == "PUT":
            return self._put_blob(request, path.rsplit("/", 1)[-1])
        if path == "/shares" and method == "POST":
            return self._create_share(request)
        if path.startswith("/shares/") and method in ("PATCH", "DELETE"):
            return self._change_share(request, path.split("/")[2])
        if path == "/workflows" and method == "POST":
            return self._workflow(request, None)
        if path.startswith("/workflows/") and path.endswith("/versions") and method == "POST":
            return self._workflow(request, path.split("/")[2])
        if path == "/assets" and method == "POST":
            return self._submit_asset(request, None)
        if path.startswith("/assets/") and path.endswith("/versions") and method == "POST":
            return self._submit_asset(request, path.split("/")[2])
        if path == "/plugins" and method == "POST":
            return self._plugin(request)
        return _error(404, "not_found")

    def _device_code(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body.get("client_name"), body
        device_code = "dc-" + secrets.token_hex(8)
        user_code = f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
        with self.lock:
            self.devices[device_code] = DeviceCode(user_code=user_code)
        return httpx.Response(200, json={
            "device_code": device_code, "user_code": user_code,
            "verification_uri": f"/zh/device?code={user_code}", "expires_in": 600, "interval": 5,
        })

    def _device_token(self, request: httpx.Request) -> httpx.Response:
        device_code = json.loads(request.content)["device_code"]
        with self.lock:
            state = self.devices.get(device_code)
            if state is None or state.expired:
                return _error(410, "expired_token")
            if state.slow_downs > 0:
                state.slow_downs -= 1
                return _error(400, "slow_down")
            if state.denied:
                return _error(403, "access_denied")
            if not state.approved:
                return _error(428, "authorization_pending")
            del self.devices[device_code]
            session = Session(id="s-" + secrets.token_hex(4), user=dict(self.user))
            self.sessions[session.id] = session
            return httpx.Response(200, json=self._pair(session))

    def _refresh(self, request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-requested-with"), "刷新接口要带 X-Requested-With"
        token = json.loads(request.content).get("refresh_token", "")
        if self.refresh_delay:
            time.sleep(self.refresh_delay)
        with self.lock:
            if self.refresh_status is not None:
                return _error(self.refresh_status, "boom")
            entry = self.refresh_tokens.get(token)
            if entry is None:
                return _error(401, "invalid_refresh_token")
            sid, used = entry
            session = self.sessions[sid]
            if session.revoked:
                return _error(401, "session_revoked")
            if used:
                # 重用一个已经换掉的刷新令牌:判盗,整个会话吊销。
                session.revoked = True
                return _error(401, "refresh_token_reused")
            entry[1] = True
            return httpx.Response(200, json=self._pair(session))

    # --- 分享 -------------------------------------------------------------------

    def _uploads(self, request: httpx.Request) -> httpx.Response:
        files = json.loads(request.content)["files"]
        with self.lock:
            self.upload_requests.append([one["sha256"] for one in files])
            missing = [one for one in files if one["sha256"] not in self.blobs]
        base = f"{STORAGE}/put" if self.presigned else f"{PREFIX}/uploads"
        return httpx.Response(200, json={"uploads": [
            {"sha256": one["sha256"], "url": f"{base}/{one['sha256']}", "headers": {"x-upload-token": "t"}}
            for one in missing
        ]})

    def _put_blob(self, request: httpx.Request, digest: str) -> httpx.Response:
        if self.presigned:
            assert "authorization" not in request.headers, "预签名地址上不该带访问令牌"
        body = request.read()
        with self.lock:
            left = self.put_failures.get(digest, 0)
            if left > 0:
                self.put_failures[digest] = left - 1
                return httpx.Response(503)
            if hashlib.sha256(body).hexdigest() != digest:
                return _error(422, "hash_mismatch")
            assert request.headers.get("content-length") == str(len(body))
            self.blobs[digest] = body
            self.puts.append(digest)
        if self.on_put is not None:
            self.on_put(digest)
        return httpx.Response(200)

    def _create_share(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        snapshot = body["snapshot"]
        assert snapshot["schema"] == "mosael.board-snapshot/1"
        assert set(snapshot) == {"schema", "viewport", "items", "edges"}
        # id 的字符集和社区服务的校验一致(mosael-formats 的 board_snapshot.ID_RE)。
        for entry in (*snapshot["items"], *snapshot["edges"]):
            if not re.match(r"^[A-Za-z0-9_.:-]{1,128}$", entry["id"]):
                return _error(422, "invalid_snapshot", entry["id"])
        referenced = set()
        for item in snapshot["items"]:
            for key in ("media", "preview"):
                if isinstance(item.get(key), dict):
                    referenced.add(item[key]["sha256"])
                    if item[key].get("thumb_sha256"):
                        referenced.add(item[key]["thumb_sha256"])
        with self.lock:
            missing = referenced - set(self.blobs)
            if missing:
                return _error(422, "missing_files", ",".join(sorted(missing)))
            share = next((one for one in self.shares.values() if one.board_key == body["board_key"] and not one.withdrawn), None)
            if share is None:
                share = Share(slug=f"b{next(self._slugs)}", board_key=body["board_key"], title=body["title"],
                              visibility=body["visibility"])
                self.shares[share.slug] = share
            share.title, share.visibility = body["title"], body["visibility"]
            share.versions.append(snapshot)
            return httpx.Response(201, json={"slug": share.slug, "url": f"/zh/b/{share.slug}", "version": len(share.versions)})

    def _change_share(self, request: httpx.Request, slug: str) -> httpx.Response:
        with self.lock:
            share = self.shares.get(slug)
            if share is None or share.withdrawn:
                return _error(404, "not_found")
            if request.method == "DELETE":
                share.withdrawn = True
                return httpx.Response(204)
            body = json.loads(request.content)
            share.title = body.get("title", share.title)
            share.visibility = body.get("visibility", share.visibility)
            return httpx.Response(200, json={"slug": slug, "title": share.title, "visibility": share.visibility})

    # --- 提交 -------------------------------------------------------------------

    def _workflow(self, request: httpx.Request, slug: str | None) -> httpx.Response:
        fields, files = parse_multipart(request)
        document = json.loads(files["file"][1])
        assert document["format"] == "mosael-workflow"
        with self.lock:
            if slug is None:
                slug = f"wf{next(self._slugs)}"
                self.workflows[slug] = {"versions": []}
            elif slug not in self.workflows:
                return _error(404, "not_found")
            entry = self.workflows[slug]
            entry["versions"].append({"fields": fields, "document": document, "cover": files.get("cover")})
            number = len(entry["versions"])
            submission = {"number": number, "version": str(number), "status": "approved"}
            if number == 1:
                # 新建:回条目详情(没有网页地址),这一次提交在 `submission` 里。
                return httpx.Response(201, json={"kind": "workflow", "slug": slug, "title": fields.get("title"),
                                                 "version": str(number), "submission": submission})
            # 新版本:只回这一版,不带 slug。
            return httpx.Response(201, json=submission)

    def _plugin(self, request: httpx.Request) -> httpx.Response:
        fields, files = parse_multipart(request)
        with self.lock:
            self.plugins.append({"fields": fields, "zip": files["file"][1], "filename": files["file"][0]})
            return httpx.Response(201, json={"slug": "demo", "url": "/zh/plugins/demo", "version": "1.0.0",
                                             "status": "pending"})

    # --- 资产 -------------------------------------------------------------------

    def publish_asset(self, bundle: dict[str, Any], files: dict[str, bytes], *, slug: str = "") -> str:
        """测试里直接在社区上放一条(别人发的)资产:图先进存储,再上架。"""
        with self.lock:
            self.blobs.update(files)
            slug = slug or f"as{next(self._slugs)}"
            entry = self.assets.setdefault(slug, {"asset_kind": bundle["kind"], "status": "approved", "versions": []})
            entry["versions"].append({"bundle": bundle, "consent_kind": None})
            return slug

    def _submit_asset(self, request: httpx.Request, slug: str | None) -> httpx.Response:
        from mosael_formats import asset_bundle
        from mosael_formats.i18n import FormatError

        body = json.loads(request.content)
        bundle = body["bundle"]
        try:
            summary = asset_bundle.validate_bundle(bundle)
            asset_bundle.check_consent(summary, body.get("consent_kind"))
        except FormatError as exc:
            return _error(422, "invalid_asset_bundle", str(exc))
        with self.lock:
            missing = set(summary.hashes) - set(self.blobs)
            if missing:
                return _error(422, "unknown_blob", ",".join(sorted(missing)))
            if slug is None:
                slug = f"as{next(self._slugs)}"
                self.assets[slug] = {"asset_kind": summary.kind, "status": "approved", "versions": []}
            elif slug not in self.assets:
                return _error(404, "not_found")
            entry = self.assets[slug]
            if entry["asset_kind"] != summary.kind:
                return _error(422, "asset_kind_changed")
            status = "pending" if summary.real_person else "approved"
            entry["status"] = status
            entry["versions"].append({"bundle": bundle, "consent_kind": body.get("consent_kind"), "fields": body})
            number = len(entry["versions"])
            submission = {"number": number, "version": str(number), "status": status}
            if number == 1:
                return httpx.Response(201, json={"kind": "asset", "slug": slug, "asset_kind": summary.kind,
                                                 "submission": submission})
            return httpx.Response(201, json=submission)

    def _asset_summary(self, slug: str, entry: dict[str, Any]) -> dict[str, Any]:
        bundle = entry["versions"][-1]["bundle"]
        return {
            "kind": "asset", "slug": slug, "title": bundle["name"], "summary": bundle.get("description", ""),
            "asset_kind": entry["asset_kind"], "real_person": bool(bundle["attributes"].get("real_person")),
            "cover_url": f"/media/{bundle['cover_sha256']}", "reference_count": len(bundle["references"]),
            "variant_count": len(bundle.get("variants") or []), "downloads": 0,
            "version": str(len(entry["versions"])), "author": {"handle": "bob", "display_name": "Bob"},
        }

    def _public_asset(self, request: httpx.Request, path: str) -> httpx.Response:
        parts = [part for part in path.split("/") if part]
        with self.lock:
            public = {slug: entry for slug, entry in self.assets.items() if entry["status"] == "approved"}
            if len(parts) == 1:
                kind = request.url.params.get("asset_kind", "")
                items = [self._asset_summary(slug, entry) for slug, entry in public.items()
                         if not kind or entry["asset_kind"] == kind]
                return httpx.Response(200, json={"items": items, "next_cursor": None})
            entry = public.get(parts[1])
            if entry is None:
                return _error(404, "not_found")
            if len(parts) == 2:
                return httpx.Response(200, json=self._asset_summary(parts[1], entry))
            if len(parts) == 3 and parts[2] == "download":
                bundle = entry["versions"][-1]["bundle"]
                hashes = {one["sha256"] for one in bundle["references"]}
                for variant in bundle.get("variants") or []:
                    hashes |= {one["sha256"] for one in variant["references"]}
                media = {digest: {"url": f"{STORAGE}/media/{digest}"} for digest in hashes}
                return httpx.Response(200, json={"slug": parts[1], "version": str(len(entry["versions"])),
                                                 "bundle": bundle, "media": media})
        return _error(404, "not_found")

    def _get_blob(self, digest: str) -> httpx.Response:
        with self.lock:
            data = self.blobs.get(digest)
        if data is None:
            return httpx.Response(404)
        if digest in self.tampered:
            data = data + b"tampered"
        return httpx.Response(200, content=data)


class Clock:
    """一个可以拨的墙钟,替换 `accounts.clock`(设备授权的节流、访问令牌的提前续期都看它)。"""

    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def install(monkeypatch: Any, fake: FakeCommunity | None = None) -> tuple[FakeCommunity, Any, Clock]:
    """把应用接到一个假社区上:重建测试库、登录、把部署设置里的社区地址指向它。"""
    from app.core.db import SessionLocal
    from app.domain import deployment
    from app.domain.community import accounts, device, shares, transport
    from tests.util import fresh_client

    fake = fake or FakeCommunity()
    clock = Clock()
    monkeypatch.setattr(transport, "make_client", fake.client)
    monkeypatch.setattr(accounts, "clock", clock)
    monkeypatch.setattr(shares, "pause", lambda _seconds: None)
    accounts.reset_for_tests()
    device.reset_for_tests()
    client = fresh_client()
    with SessionLocal() as db:
        deployment.set_community_url(db, ORIGIN)
        db.commit()
    return fake, client, clock


def connect(client: Any, fake: FakeCommunity, clock: Clock) -> dict[str, Any]:
    """走一遍设备授权,连上。回连上之后的状态。"""
    started = client.post("/api/community/connect")
    assert started.status_code == 200, started.text
    fake.approve(started.json()["user_code"])
    clock.advance(5)
    polled = client.post("/api/community/connect/poll")
    assert polled.status_code == 200, polled.text
    assert polled.json()["state"] == "connected", polled.json()
    return polled.json()["status"]
