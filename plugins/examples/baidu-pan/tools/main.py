"""百度网盘 —— 把网盘里的素材拉进素材库。

**只做「拉进来」,不做上传。** 上传涉及分片、断点、秒传(要算文件 md5 和 slice-md5),
是完全另一摊工作量;而日常真正在做的事是「把网盘里的素材拉进来剪」。

## 为什么 pan_import 不自己下载

它只换到 dlink 就交给宿主(见 docs/PLUGIN_MANIFEST 的 artifact 那节)。理由不是省事:
进度、取消、重试、大小上限、失败隔离,宿主的任务机制里全都有,而插件这一侧只有一次
60 秒的 stdio 调用 —— 自己下一个 2GB 的文件必然超时,就算不超时,用户也看不到任何进度,
按取消也停不下来。

dlink 恰好是**必须带凭据才能下**的那种地址:不带 User-Agent 直接 403,还要拼上 access_token。
所以交出去的不只是 url,还有那组请求头。

## 关于凭据

百度的 access_token 三十天到期。用户只填一次 refresh_token(有效期十年),之后由插件
自己续:撞上「过期」那个 errno 就换一个新的、原样重试一次,并把换来的 access_token
**和新的 refresh_token** 一起交回 `state`,宿主替它记住(见 docs/PLUGIN_MANIFEST 的
state 那节)。

**两个都要交回去**:百度换 token 时会连 refresh_token 一起轮换。只存 access_token 的话,
三十天后拿着一个已经作废的 refresh_token 去换,得到的是一个查不出原因的失败。
"""

import json
import os
import sys
import urllib.parse
import urllib.request

API_ROOT = "https://pan.baidu.com/rest/2.0/xpan"
OAUTH_URL = "https://openapi.baidu.com/oauth/2.0/token"
# 百度的下载接口认这个 UA。不带的话 dlink 直接回 403,而错误里不会说是为什么。
DOWNLOAD_UA = "pan.baidu.com"
TIMEOUT_SECONDS = 20


class PanError(Exception):
    """面向用户的失败。消息会原样显示在调用记录里。"""


#: 这次调用期间用的 access_token,以及要交回去记住的东西。**模块级**是有意的:
#: 一次进程只处理一个请求,而刷新可能发生在调用链深处(_call 里),结果要能传到 main 那一层。
_SESSION = {"access_token": "", "state": {}}


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
    refresh = (os.environ.get("BAIDU_PAN_REFRESH_TOKEN") or "").strip()
    if not (app_key and secret and refresh):
        raise PanError("没有配置 AppKey / SecretKey / RefreshToken —— 打开设置里这个连接填上")
    query = urllib.parse.urlencode(
        {"grant_type": "refresh_token", "refresh_token": refresh, "client_id": app_key, "client_secret": secret}
    )
    request = urllib.request.Request(f"{OAUTH_URL}?{query}", headers={"User-Agent": DOWNLOAD_UA})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise PanError(f"续 access_token 失败:{exc}") from exc
    if payload.get("error"):
        raise PanError(
            f"续 access_token 被拒:{payload.get('error_description') or payload['error']}"
            " —— refresh_token 可能已作废,回设置里重新走一次授权"
        )
    access = str(payload.get("access_token") or "")
    if not access:
        raise PanError("百度没有返回新的 access_token")
    _SESSION["access_token"] = access
    _SESSION["state"]["BAIDU_PAN_ACCESS_TOKEN"] = access
    # 百度会连 refresh_token 一起轮换。不记的话,三十天后拿着一个作废的去换,
    # 得到的是一个查不出原因的失败。
    rotated = str(payload.get("refresh_token") or "")
    if rotated and rotated != refresh:
        _SESSION["state"]["BAIDU_PAN_REFRESH_TOKEN"] = rotated


def _root() -> str:
    return (os.environ.get("BAIDU_PAN_ROOT") or "/").strip() or "/"


#: 百度用 errno 表达失败,HTTP 状态码永远是 200。挑几个最常撞上的翻成人话 ——
#: 光报一个数字等于让用户去搜,而这几个的处置方式完全不同。
ERRNO_MESSAGES = {
    -6: "access_token 无效(续了一次仍然不行,回设置里检查 AppKey / RefreshToken)",
    -9: "文件不存在,可能已经被移走或删掉了",
    2: "百度网盘接口拒绝了这次请求(参数不对)",
    111: "access_token 已过期(续了一次仍然不行,回设置里检查 AppKey / RefreshToken)",
    31034: "调用太频繁,被百度限流了,过一会儿再试",
}

#: 「令牌不行了」的那几个 errno。撞上就续一次、原样重试 —— 再不行才报出去。
EXPIRED_ERRNOS = (-6, 111)


def _call(path: str, params: dict, *, allow_refresh: bool = True) -> dict:
    query = urllib.parse.urlencode({**params, "access_token": _token()})
    request = urllib.request.Request(f"{API_ROOT}{path}?{query}", headers={"User-Agent": DOWNLOAD_UA})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # 网络、超时、非 JSON —— 都是这次调用的失败
        raise PanError(f"百度网盘接口没有响应:{exc}") from exc
    errno = payload.get("errno")
    if errno in EXPIRED_ERRNOS and allow_refresh:
        # 续一次、原样重试一次。**只重试一次** —— 续完还是过期说明问题不在有效期上
        # (AppKey 不对、应用被停用),再试就是拿同一个错误刷接口。
        _refresh()
        return _call(path, params, allow_refresh=False)
    if errno not in (0, None):
        raise PanError(ERRNO_MESSAGES.get(errno, f"百度网盘接口返回 errno={errno}"))
    return payload


def _entry(item: dict) -> dict:
    """一条列表项。只留调用方真正要用的那几样 —— 原样透传的话,模型要在几十个字段里找 fs_id。"""
    return {
        "fs_id": str(item.get("fs_id") or ""),
        "name": item.get("server_filename") or item.get("filename") or "",
        "path": item.get("path") or "",
        "is_dir": bool(item.get("isdir")),
        "size": int(item.get("size") or 0),
    }


def pan_list(payload: dict) -> dict:
    path = str(payload.get("path") or "").strip() or _root()
    limit = max(1, min(int(payload.get("limit") or 100), 1000))
    data = _call("/file", {"method": "list", "dir": path, "limit": limit})
    return {"path": path, "entries": [_entry(one) for one in data.get("list") or []]}


def pan_search(payload: dict) -> dict:
    keyword = str(payload.get("keyword") or "").strip()
    if not keyword:
        raise PanError("keyword 不能为空")
    params = {"method": "search", "key": keyword, "recursion": 1}
    path = str(payload.get("path") or "").strip()
    if path:
        params["dir"] = path
    data = _call("/file", {**params})
    return {"keyword": keyword, "entries": [_entry(one) for one in data.get("list") or []]}


def pan_import(payload: dict) -> dict:
    """换到 dlink,交给宿主去下。

    dlink 要单独一次 filemetas 调用才拿得到 —— 列表接口不给它(它是有时效的临时地址,
    列一次目录就签一百个出来没有意义)。
    """
    fs_id = str(payload.get("fs_id") or "").strip()
    if not fs_id:
        raise PanError("fs_id 不能为空")
    data = _call("/multimedia", {"method": "filemetas", "fsids": json.dumps([int(fs_id)]), "dlink": 1})
    items = data.get("list") or []
    if not items:
        raise PanError("这个 fs_id 在网盘里找不到")
    item = items[0]
    dlink = str(item.get("dlink") or "")
    if not dlink:
        raise PanError("百度没有给出下载地址(可能是目录,或者这个文件没有下载权限)")
    name = item.get("server_filename") or item.get("filename") or f"baidu-{fs_id}"
    return {
        # 交给宿主搬字节。**access_token 拼在 url 上、UA 放在头里** —— 两样缺一个都是 403,
        # 而百度不会告诉你缺的是哪一个。
        "artifact": {
            "url": f"{dlink}&access_token={_token()}",
            "headers": {"User-Agent": DOWNLOAD_UA},
            "filename": name,
        },
        "fs_id": fs_id,
        "size": int(item.get("size") or 0),
    }


TOOLS = {"pan_list": pan_list, "pan_search": pan_search, "pan_import": pan_import}


def main() -> None:
    request = json.loads(sys.stdin.read())
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
        json.dump({"ok": False, "error": str(exc)}, sys.stdout, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001 — 插件不该把栈吐给用户
        json.dump({"ok": False, "error": f"插件内部错误:{exc}"}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
