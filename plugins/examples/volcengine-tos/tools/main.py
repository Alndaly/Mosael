"""火山引擎 TOS —— 把素材传上去、换一条公网直链,以及把桶里的东西拉回素材库。

## 它是为什么存在的

Mosael 是本地优先的:素材库里的文件在你自己的盘上,**没有公网地址**。而有些供应商只收链接 ——
方舟 Seedance 的参考视频就是一例(官方文档:「请确保 URL 是公网可公开访问的链接」),
它收公网 http(s) 直链,**明确不收 Base64**。

**这一家尤其对得上号**:方舟自己的文档就推荐「存放在 TOS 对象存储服务中,
并配置为公共读」。`tos_upload` 就是那座桥:传上去,交回一条**限时**直链(签名在查询串里,桶不必设成公共读),
直接粘进生成节点的「参考视频」那一格。

签名是纯标准库手写的(见 sigv4.py)—— 插件进程里没有 boto3,也不该为了签四个请求装一整个 SDK。
"""
from __future__ import annotations

import os

import sigv4
import storage
from storage import StorageError, line


def _bucket() -> storage.Bucket:
    region = os.environ.get("TOS_REGION", "cn-beijing").strip() or "cn-beijing"
    endpoint = os.environ.get("TOS_ENDPOINT", "").strip() or f"tos-{region}.volces.com"
    return storage.Bucket(
        flavor=sigv4.TOS,
        endpoint=endpoint,
        bucket=os.environ.get("TOS_BUCKET", "").strip(),
        region=region,
        access_key=os.environ.get("TOS_ACCESS_KEY", "").strip(),
        secret=os.environ.get("TOS_SECRET_KEY", "").strip(),
    )


def upload(payload: dict, locale: str) -> dict:
    path = str(payload.get("asset_id") or "").strip()   # 宿主把素材换成了一个本地绝对路径
    if not path or not os.path.isfile(path):
        raise StorageError(line(locale, "没有拿到要上传的素材", "No asset to upload"))
    key = str(payload.get("key") or "").strip() or f"mosael/{os.path.basename(path)}"
    expires = int(payload.get("expires") or storage.DEFAULT_EXPIRES)
    bucket = _bucket()
    with open(path, "rb") as handle:
        bucket.put(key, handle.read(), content_type=storage.content_type_of(path))
    signed = bucket.presign(key, expires=expires)
    return {
        "key": key,
        "url": signed,
        "public_url": bucket.public_url(key),
        "expires_in": expires,
        "summary": line(
            locale,
            f"已传到 tos://{bucket.bucket}/{key},直链 {expires} 秒内有效",
            f"Uploaded to tos://{bucket.bucket}/{key}; the link is valid for {expires}s",
        ),
    }


def presign(payload: dict, locale: str) -> dict:
    key = str(payload.get("key") or "").strip()
    if not key:
        raise StorageError(line(locale, "要给哪个对象签链接?", "Which object should I sign?"))
    expires = int(payload.get("expires") or storage.DEFAULT_EXPIRES)
    url = _bucket().presign(key, expires=expires)
    return {"key": key, "url": url, "expires_in": expires,
            "summary": line(locale, f"{expires} 秒内有效的直链", f"A direct link valid for {expires}s")}


def fetch(payload: dict, locale: str) -> dict:
    """把桶里的一个对象拉回素材库。

    **交回的是地址,不是字节** —— 让宿主去搬:进度、取消、重试、大小上限、失败隔离,
    它的任务机制里全都有,而插件这一侧只有一次短命的 stdio 调用(见 docs/PLUGIN_MANIFEST)。
    """
    key = str(payload.get("key") or "").strip()
    if not key:
        raise StorageError(line(locale, "要拉哪个对象?", "Which object should I fetch?"))
    url = _bucket().presign(key, expires=storage.DEFAULT_EXPIRES)
    return {"artifact": {"url": url, "filename": os.path.basename(key) or "object"},
            "summary": line(locale, f"已取回 {key}", f"Fetched {key}")}


def listing(payload: dict, locale: str) -> dict:
    items = _bucket().listing(str(payload.get("prefix") or ""), int(payload.get("limit") or 100))
    return {"items": items, "count": len(items),
            "summary": line(locale, f"{len(items)} 个对象", f"{len(items)} objects")}


if __name__ == "__main__":
    storage.run({"tos_upload": upload, "tos_presign": presign, "tos_fetch": fetch, "tos_list": listing})
