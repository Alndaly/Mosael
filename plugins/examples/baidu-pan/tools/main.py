"""百度网盘 —— 在网盘和素材库之间搬文件。

拉:`pan_list` / `pan_search` 找到 fs_id,`pan_import` 导进来。
传:`pan_upload` 把素材库里的东西存到网盘。

## 上传为什么是三步

百度的上传协议本身就是三步,不是我们绕远:

1. `precreate` —— 报上文件大小和**每个分片的 md5**,百度回一个 uploadid;
   秒传就发生在这一步:它认得这些 md5 的话直接回 `return_type=2`,一个字节都不用传。
2. `superfile2` —— 逐片传。分片固定 4MB(百度的规定,不是我们挑的)。
3. `create` —— 报上 uploadid 和分片清单,文件才算落地。

少一步都不行:只传不 create 的话,文件在网盘上根本不存在,而 superfile2 全都返回成功。

上传是**流式工具**(见 docs/PLUGIN_MANIFEST 的「流式工具」):每传完一片报一次进度,宿主建了取消文件
就在片与片之间停下。清单给它声明了 30 分钟的预算 —— 此前没声明,几百 MB 的成片在默认的 60 秒里必然超时。

## 为什么 pan_import 不自己下载

它只换到 dlink 就交给宿主(见 docs/PLUGIN_MANIFEST 的 artifact 那节)。理由不是省事:
进度、取消、重试、大小上限、失败隔离,宿主的任务机制里全都有,而插件这一侧只有一次
短命的 stdio 调用 —— 自己下一个 2GB 的文件必然超时,就算不超时,用户也看不到任何进度,
按取消也停不下来。

dlink 恰好是**必须带凭据才能下**的那种地址:不带 User-Agent 直接 403,还要拼上 access_token。
所以交出去的不只是 url,还有那组请求头。

## 关于凭据

百度的 access_token 三十天到期。用户只填一次 refresh_token(有效期十年),之后由插件
自己续:撞上「过期」那个 errno 就换一个新的、原样重试一次,并把换来的 access_token
**和新的 refresh_token** 一起交回 `state`,宿主替它记住(见 docs/PLUGIN_MANIFEST 的
state 那节)。**每一条接口都走同一个口子**(_api):此前上传的 precreate / create 绕开了它,
令牌一过期,列目录、导入会自己续好,上传却直接报错。

**两个都要交回去**:百度换 token 时会连 refresh_token 一起轮换。只存 access_token 的话,
三十天后拿着一个已经作废的 refresh_token 去换,得到的是一个查不出原因的失败。
"""

import hashlib
import json
import os
import sys
import urllib.parse
import urllib.request
import uuid

API_ROOT = "https://pan.baidu.com/rest/2.0/xpan"
OAUTH_URL = "https://openapi.baidu.com/oauth/2.0/token"
# 百度的下载接口认这个 UA。不带的话 dlink 直接回 403,而错误里不会说是为什么。
DOWNLOAD_UA = "pan.baidu.com"
TIMEOUT_SECONDS = 20
CANCEL_ENV = "MOSAEL_PLUGIN_CANCEL_FILE"


class PanError(Exception):
    """面向用户的失败。消息会原样显示在调用记录里。"""


class NeedsReauthorization(PanError):
    """百度不再接受已存的令牌:refresh_token 换不出新的,或者续完了照样说过期。

    响应里带 `reauthorize: true`,宿主据此把这个连接标成「需要重新授权」(见 docs/PLUGIN_MANIFEST
    的 `instance.oauth` 那节)—— 这句话写在调用记录里,而用户看的是连接卡片。
    """


#: 这次调用期间用的 access_token、要交回去记住的东西,以及调用方的语言。**模块级**是有意的:
#: 一次进程只处理一个请求,而刷新可能发生在调用链深处(_api 里),结果要能传到 main 那一层。
_SESSION = {"access_token": "", "state": {}, "locale": "zh"}


def _t(zh: str, en: str) -> str:
    """一句给人看的话,按调用方的语言挑(`zh-CN` 和 `zh` 是同一件事)。"""
    return zh if str(_SESSION["locale"]).replace("_", "-").split("-")[0].lower() == "zh" else en


def _token() -> str:
    if not _SESSION["access_token"]:
        _SESSION["access_token"] = (os.environ.get("BAIDU_PAN_ACCESS_TOKEN") or "").strip()
    if not _SESSION["access_token"]:
        # 一个都没有:第一次用,直接去换。
        _refresh()
    return _SESSION["access_token"]


def _refresh() -> None:
    """拿 refresh_token 换一份新的。换来的两个 token 都记进 _SESSION["state"]。"""
    app_key = (os.environ.get("BAIDU_PAN_APP_KEY") or "").strip()
    secret = (os.environ.get("BAIDU_PAN_SECRET_KEY") or "").strip()
    # 这一次调用里已经轮换过的话,手里那个才是有效的(环境变量里的已经作废)。
    refresh = (_SESSION["state"].get("BAIDU_PAN_REFRESH_TOKEN") or os.environ.get("BAIDU_PAN_REFRESH_TOKEN") or "").strip()
    if not (app_key and secret and refresh):
        raise PanError(_t("没有配置 AppKey / SecretKey / RefreshToken —— 打开设置里这个连接填上",
                          "AppKey / SecretKey / RefreshToken are not set — fill them in on this connection"))
    query = urllib.parse.urlencode(
        {"grant_type": "refresh_token", "refresh_token": refresh, "client_id": app_key, "client_secret": secret}
    )
    request = urllib.request.Request(f"{OAUTH_URL}?{query}", headers={"User-Agent": DOWNLOAD_UA})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise PanError(_t(f"续 access_token 失败:{exc}", f"Could not renew the access_token: {exc}")) from exc
    if payload.get("error"):
        reason = payload.get("error_description") or payload["error"]
        raise NeedsReauthorization(_t(
            f"续 access_token 被拒:{reason} —— refresh_token 可能已作废,回设置里重新走一次授权",
            f"Renewing the access_token was refused: {reason} — the refresh_token may be revoked; "
            "authorize again on this connection",
        ))
    access = str(payload.get("access_token") or "")
    if not access:
        raise PanError(_t("百度没有返回新的 access_token", "Baidu returned no new access_token"))
    _SESSION["access_token"] = access
    _SESSION["state"]["BAIDU_PAN_ACCESS_TOKEN"] = access
    # 百度会连 refresh_token 一起轮换。不记的话,三十天后拿着一个作废的去换,
    # 得到的是一个查不出原因的失败。
    rotated = str(payload.get("refresh_token") or "")
    if rotated and rotated != refresh:
        _SESSION["state"]["BAIDU_PAN_REFRESH_TOKEN"] = rotated


#: 百度用 errno 表达失败,HTTP 状态码永远是 200。挑常撞上的翻成人话 —— 光报一个数字等于让用户去搜,
#: 而这几个的处置方式完全不同。出处:开放平台文档的「错误码」一节。
ERRNO_MESSAGES = {
    -6: ("access_token 无效(续了一次仍然不行,回设置里检查 AppKey / RefreshToken)",
         "The access_token is invalid (still failing after one renewal — check AppKey / RefreshToken)"),
    -7: ("文件或目录名不对,或者没有权限访问", "Bad file or folder name, or no permission to access it"),
    -8: ("网盘上已经有同名的文件或目录", "A file or folder with that name already exists"),
    -9: ("文件不存在,可能已经被移走或删掉了", "The file does not exist — it may have been moved or deleted"),
    2: ("百度网盘接口拒绝了这次请求(参数不对)", "Baidu Netdisk rejected the request (bad parameters)"),
    111: ("access_token 已过期(续了一次仍然不行,回设置里检查 AppKey / RefreshToken)",
          "The access_token has expired (still failing after one renewal — check AppKey / RefreshToken)"),
    31034: ("调用太频繁,被百度限流了,过一会儿再试", "Rate-limited by Baidu — try again in a moment"),
    31066: ("文件不存在,可能已经被移走或删掉了", "The file does not exist — it may have been moved or deleted"),
}

#: 「令牌不行了」的那几个 errno。撞上就续一次、原样重试 —— 再不行才报出去。
EXPIRED_ERRNOS = (-6, 111)


def _explain(errno, what: str = "") -> str:
    known = ERRNO_MESSAGES.get(errno)
    if known:
        return _t(*known)
    prefix = f"{what} " if what else ""
    return _t(f"{prefix}百度网盘接口返回 errno={errno}", f"{prefix}Baidu Netdisk returned errno={errno}")


def _http(url: str, *, body=None, headers=None, timeout: float = TIMEOUT_SECONDS) -> dict:
    request = urllib.request.Request(url, data=body, headers={"User-Agent": DOWNLOAD_UA, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # 网络、超时、非 JSON —— 都是这次调用的失败
        raise PanError(_t(f"百度网盘接口没有响应:{exc}", f"Baidu Netdisk did not respond: {exc}")) from exc


def _api(path: str, params: dict, *, form=None, allow_refresh: bool = True) -> dict:
    """调一次开放平台接口(`form` 给了就是 POST 表单)。**所有接口走这一个口子**:令牌过期就续一次、原样重试。"""
    query = urllib.parse.urlencode({**params, "access_token": _token()})
    body = urllib.parse.urlencode(form).encode() if form is not None else None
    payload = _http(f"{API_ROOT}{path}?{query}", body=body)
    errno = payload.get("errno")
    if errno in EXPIRED_ERRNOS and allow_refresh:
        # 续一次、原样重试一次。**只重试一次** —— 续完还是过期说明问题不在有效期上
        # (AppKey 不对、应用被停用),再试就是拿同一个错误刷接口。
        _refresh()
        return _api(path, params, form=form, allow_refresh=False)
    if errno in EXPIRED_ERRNOS:
        # 续过一次还是不认:问题不在有效期上,令牌这条路走不通了。
        raise NeedsReauthorization(_explain(errno, params.get("method", "")))
    if errno not in (0, None):
        raise PanError(_explain(errno, params.get("method", "")))
    return payload


def _limit(payload: dict) -> int:
    try:
        return max(1, min(int(payload.get("limit") or 100), 1000))
    except (TypeError, ValueError):
        return 100


def _entry(item: dict) -> dict:
    """一条列表项。只留调用方真正要用的那几样 —— 原样透传的话,模型要在几十个字段里找 fs_id。"""
    return {
        "fs_id": str(item.get("fs_id") or ""),
        "name": item.get("server_filename") or item.get("filename") or "",
        "path": item.get("path") or "",
        "is_dir": bool(item.get("isdir")),
        "size": int(item.get("size") or 0),
    }


def _absolute(path: str) -> str:
    """网盘路径一律从根写起。`我的资源/成片.mp4` 这种相对写法百度按参数错误拒掉,而错误里不说为什么。"""
    path = path.strip()
    return path if path.startswith("/") else f"/{path}"


def pan_list(payload: dict) -> dict:
    # 不给路径就从网盘根目录列起。**这里曾经有一个「起始目录」配置项**,而它只在这一行
    # 起作用:既不限制智能体去别的目录(它照样可以传 path),也不省事(不指定路径时,
    # 列根目录和列某个子目录,下一步都要继续往里翻)。名字听起来像一道边界,实际是一个
    # 默认值 —— 占着设置页一整行去解释一件它没做的事。真要把智能体圈在某个目录里,那是
    # 另一回事:得让**所有**路径操作都受限,而不是只改这一个兜底值。
    path = _absolute(str(payload.get("path") or "/"))
    limit = _limit(payload)
    try:
        start = max(0, int(payload.get("start") or 0))
    except (TypeError, ValueError):
        start = 0
    data = _api("/file", {"method": "list", "dir": path, "start": start, "limit": limit})
    entries = [_entry(one) for one in data.get("list") or []]
    # **限制由我们兜底,不指望对方。** 百度这个接口收下 limit 却不照办:实测 limit=2 和
    # limit=10 都回了根目录全部 57 条。原因不明(参数名和文档一致),但原因不重要 —— 这个
    # 参数存在的意义是**别让几十条目录塞进模型的上下文**,而"我们问了、对方没听"对调用方
    # 来说和没这个参数完全一样。声明了就得做到,做不到的那部分自己补上。
    #
    # 仍然照样发出去:哪天它开始生效,就能少传一大段回来。
    #
    # **截掉的要说出来。** 此前只截不说:57 条里给了 2 条,调用方以为目录里就这两个。
    # 截断了、或者对方正好给满一页,都说「还有」,并给出下一页从哪儿开始。
    more = len(entries) >= limit
    out = {"path": path, "entries": entries[:limit], "has_more": more}
    if more:
        out["next_start"] = start + limit
    return out


def pan_search(payload: dict) -> dict:
    keyword = str(payload.get("keyword") or "").strip()
    if not keyword:
        raise PanError(_t("keyword 不能为空", "keyword must not be empty"))
    limit = _limit(payload)
    params = {"method": "search", "key": keyword, "recursion": 1}
    path = str(payload.get("path") or "").strip()
    if path:
        params["dir"] = _absolute(path)
    data = _api("/file", params)
    entries = [_entry(one) for one in data.get("list") or []]
    # 和 pan_list 同一个道理:**限制由我们兜底**。搜索天然会命中一大片(实测一个词回了 50 条),
    # 而这些条目是直接进模型上下文的 —— 一次没约束的搜索能顶掉半个对话的可用篇幅。
    # 这里不往请求里塞 limit:search 的每页条数(`num`)不由调用方定,凭空发一个只会让人以为是它在起作用。
    # 截掉的照样说出来(对方自己也说「还有」时同理),让调用方知道该缩小关键词或限定目录。
    return {"keyword": keyword, "entries": entries[:limit],
            "has_more": len(entries) > limit or bool(data.get("has_more"))}


def pan_import(payload: dict) -> dict:
    """换到 dlink,交给宿主去下。

    dlink 要单独一次 filemetas 调用才拿得到 —— 列表接口不给它(它是有时效的临时地址,
    列一次目录就签一百个出来没有意义)。
    """
    fs_id = str(payload.get("fs_id") or "").strip()
    if not fs_id:
        raise PanError(_t("fs_id 不能为空", "fs_id must not be empty"))
    if not fs_id.isdigit():
        # 此前直接 int(),模型把文件名当 fs_id 传进来时报的是一句「插件内部错误:invalid literal」。
        raise PanError(_t(f"fs_id 是一串数字(pan_list / pan_search 给出的那个),收到的是「{fs_id}」",
                          f"fs_id is a number (the one pan_list / pan_search gives), got “{fs_id}”"))
    data = _api("/multimedia", {"method": "filemetas", "fsids": json.dumps([int(fs_id)]), "dlink": 1})
    items = data.get("list") or []
    if not items:
        raise PanError(_t("这个 fs_id 在网盘里找不到", "No file with this fs_id in the netdisk"))
    item = items[0]
    if item.get("isdir"):
        raise PanError(_t("这是一个目录,导入要的是文件 —— 先用 pan_list 往里翻",
                          "This is a folder; import takes a file — use pan_list to look inside"))
    dlink = str(item.get("dlink") or "")
    if not dlink:
        raise PanError(_t("百度没有给出下载地址(可能是目录,或者这个文件没有下载权限)",
                          "Baidu gave no download address (a folder, or no download permission)"))
    name = item.get("server_filename") or item.get("filename") or f"baidu-{fs_id}"
    joiner = "&" if "?" in dlink else "?"
    return {
        # 交给宿主搬字节。**access_token 拼在 url 上、UA 放在头里** —— 两样缺一个都是 403,
        # 而百度不会告诉你缺的是哪一个。
        "artifact": {
            "url": f"{dlink}{joiner}access_token={urllib.parse.quote(_token())}",
            "headers": {"User-Agent": DOWNLOAD_UA},
            "filename": name,
        },
        "fs_id": fs_id,
        "size": int(item.get("size") or 0),
    }


#: 百度规定的分片大小。不是可调参数 —— 换个数字 precreate 报的 md5 清单就对不上。
CHUNK_BYTES = 4 * 1024 * 1024
UPLOAD_HOST = "https://d.pcs.baidu.com"


def _chunk_md5s(path: str) -> tuple[list, int]:
    """逐片算 md5。**流式读**,不整个载进内存 —— 上传的常常是几个 G 的成片。"""
    md5s = []
    total = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            md5s.append(hashlib.md5(chunk).hexdigest())
    if not md5s:
        raise PanError(_t("这个文件是空的", "The file is empty"))
    return md5s, total


def _upload_chunk(remote_path: str, uploadid: str, index: int, data: bytes) -> None:
    """传一片。multipart 手搓 —— 标准库没有现成的,而为这一件事引一个依赖不值当。

    分隔符每片随机:写死的话,一段恰好含着那串字节的视频会把表单切断。
    """
    boundary = f"----Mosael{uuid.uuid4().hex}"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="chunk"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    body = head + data + f"\r\n--{boundary}--\r\n".encode()
    query = urllib.parse.urlencode(
        {
            "method": "upload",
            "access_token": _token(),
            "type": "tmpfile",
            "path": remote_path,
            "uploadid": uploadid,
            "partseq": index,
        }
    )
    try:
        payload = _http(f"{UPLOAD_HOST}/rest/2.0/pcs/superfile2?{query}", body=body,
                        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                        timeout=TIMEOUT_SECONDS * 6)
    except PanError as exc:
        raise PanError(_t(f"上传第 {index + 1} 片失败:{exc}", f"Uploading part {index + 1} failed: {exc}")) from exc
    if payload.get("error_code"):
        reason = payload.get("error_msg") or payload["error_code"]
        raise PanError(_t(f"上传第 {index + 1} 片被拒:{reason}", f"Part {index + 1} was rejected: {reason}"))


def _progress(fraction: float, message: str) -> None:
    """流式工具的进度行(见 docs/PLUGIN_MANIFEST 的「流式工具」)。"""
    print(json.dumps({"event": "progress", "progress": round(fraction, 4), "message": message},
                     ensure_ascii=False), flush=True)


def _cancelled() -> bool:
    flag = os.environ.get(CANCEL_ENV, "")
    return bool(flag) and os.path.exists(flag)


def pan_upload(payload: dict) -> dict:
    """素材库 → 网盘。

    `asset_id` 那个字段在清单里标了 `format: asset`,所以宿主交给我们的已经是一个**本地
    路径**(见 docs/PLUGIN_MANIFEST 的素材输入那节)—— 插件这一侧不知道素材库存在。
    """
    local = str(payload.get("asset_id") or "").strip()
    remote = str(payload.get("path") or "").strip()
    if not local:
        raise PanError(_t("没有拿到要上传的文件", "No file to upload"))
    if not remote or remote.endswith("/"):
        raise PanError(_t("path 要是网盘上的完整路径,含文件名", "path must be a full netdisk path including the file name"))
    if not os.path.isfile(local):
        raise PanError(_t("要上传的文件不存在", "The file to upload does not exist"))
    remote = _absolute(remote)

    md5s, size = _chunk_md5s(local)
    # rtype:1 = 同名另存为副本(默认),3 = 覆盖。默认不覆盖 —— 传错一次就把人家网盘上的
    # 东西冲掉,这个代价比多一个副本大得多。
    rtype = 3 if payload.get("overwrite") is True else 1

    pre = _api("/file", {"method": "precreate"},
               form={"path": remote, "size": size, "isdir": 0, "autoinit": 1, "rtype": rtype,
                     "block_list": json.dumps(md5s)})

    # 秒传:百度认得这些分片,一个字节都不用传。
    if pre.get("return_type") == 2:
        info = pre.get("info") or {}
        _progress(1.0, _t("秒传完成", "Instant upload done"))
        return {"fs_id": str(info.get("fs_id") or ""), "path": info.get("path") or remote,
                "size": size, "rapid": True}

    uploadid = str(pre.get("uploadid") or "")
    if not uploadid:
        raise PanError(_t("百度没有返回 uploadid", "Baidu returned no uploadid"))
    sent = 0
    with open(local, "rb") as handle:
        for index in range(len(md5s)):
            if _cancelled():
                # 没传完的分片百度那边自己会过期清掉(没有 create 就不存在这个文件)。
                raise PanError(_t("已取消上传", "Upload cancelled"))
            chunk = handle.read(CHUNK_BYTES)
            _upload_chunk(remote, uploadid, index, chunk)
            sent += len(chunk)
            _progress(sent / size, _t(f"已上传 {sent / 1048576:.1f} / {size / 1048576:.1f} MB",
                                      f"Uploaded {sent / 1048576:.1f} of {size / 1048576:.1f} MB"))

    created = _api("/file", {"method": "create"},
                   form={"path": remote, "size": size, "isdir": 0, "rtype": rtype,
                         "uploadid": uploadid, "block_list": json.dumps(md5s)})
    return {"fs_id": str(created.get("fs_id") or ""), "path": created.get("path") or remote,
            "size": size, "rapid": False}


TOOLS = {"pan_list": pan_list, "pan_search": pan_search, "pan_import": pan_import, "pan_upload": pan_upload}


def main() -> None:
    request = json.loads(sys.stdin.read())
    _SESSION["locale"] = str(request.get("locale") or os.environ.get("MOSAEL_LOCALE") or "zh")
    name = request.get("tool")
    handler = TOOLS.get(name)
    if handler is None:
        json.dump({"ok": False, "error": f"unknown tool: {name}"}, sys.stdout, ensure_ascii=False)
        return
    try:
        output = handler(request.get("input") or {})
        # state 和 output 平级,**不进 output**:output 会交给调用方和模型,而刚续出来的
        # 令牌不该出现在那里(见 docs/PLUGIN_MANIFEST 的 state 那节)。
        response = {"ok": True, "output": output}
        if _SESSION["state"]:
            response["state"] = _SESSION["state"]
        json.dump(response, sys.stdout, ensure_ascii=False)
    except PanError as exc:
        # 失败也要交回续出来的令牌:百度那边旧的已经作废了,这次没记住,下次就只能让用户重新授权。
        response = {"ok": False, "error": str(exc)}
        if isinstance(exc, NeedsReauthorization):
            response["reauthorize"] = True
        if _SESSION["state"]:
            response["state"] = _SESSION["state"]
        json.dump(response, sys.stdout, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — 插件不该把栈吐给用户
        json.dump({"ok": False, "error": _t(f"插件内部错误:{exc}", f"Plugin error: {exc}")}, sys.stdout,
                  ensure_ascii=False)


if __name__ == "__main__":
    main()
