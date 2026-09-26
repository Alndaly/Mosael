"""对象存储 —— 把素材传上去、换一条公网直链,以及把桶里的东西拉回素材库。

## 它是为什么存在的

Mosael 是本地优先的:素材库里的文件在你自己的盘上,**没有公网地址**。而有些供应商只收链接 ——
方舟 Seedance 的参考视频就是一例(官方文档:「请确保 URL 是公网可公开访问的链接」),
它收公网 http(s) 直链,**明确不收 Base64**。

`storage_upload` 就是那座桥:传上去,交回一条**限时**直链(签名在查询串里,桶不必设成公共读)。
它声明了 `public_url`,宿主在「只收链接」的那一格遇到本地素材时自动调它(见
backend/app/domain/generation/public_links.py)。

## 一个插件,五个选项

阿里云 OSS / 腾讯云 COS / 火山引擎 TOS / Amazon S3 / S3 兼容服务,连哪一家是**连接的配置**
(`STORAGE_PROVIDER`),不是五个插件。此前它们是四个包,主体和签名在包之间逐字节拷贝、靠一条棘轮
钉着不漂;而差异只有 providers.py 那一张表。

签名是纯标准库手写的(sigv4.py、qsign.py)—— 插件进程里没有 boto3,也不该为了签几个请求装一整个 SDK。
"""
from __future__ import annotations

import os

import storage
from providers import PROVIDERS
from storage import Reporter, StorageError, line


def _bucket(locale: str) -> storage.Bucket:
    name = os.environ.get("STORAGE_PROVIDER", "").strip()
    provider = PROVIDERS.get(name)
    if provider is None:
        raise StorageError(line(locale, "这个连接还没选是哪一家对象存储", "This connection has no storage provider chosen"))
    return storage.Bucket(
        provider=provider,
        bucket=os.environ.get("STORAGE_BUCKET", ""),
        region=os.environ.get("STORAGE_REGION", ""),
        endpoint=os.environ.get("STORAGE_ENDPOINT", ""),
        access_key=os.environ.get("STORAGE_ACCESS_KEY_ID", ""),
        secret=os.environ.get("STORAGE_ACCESS_KEY_SECRET", ""),
        locale=locale,
    )


def _where(bucket: storage.Bucket, key: str) -> str:
    return f"{bucket.provider.scheme}://{bucket.bucket}/{key}"


def upload(payload: dict, locale: str, reporter: Reporter) -> dict:
    path = str(payload.get("asset_id") or "").strip()   # 宿主把素材换成了一个本地绝对路径
    if not path or not os.path.isfile(path):
        raise StorageError(line(locale, "没有拿到要上传的素材", "No asset to upload"))
    bucket = _bucket(locale)
    expires = bucket.clamp_expires(payload.get("expires"))
    key = str(payload.get("key") or "").strip().lstrip("/")
    if not key:
        # 默认路径里带**内容指纹**:此前是 `mosael/<文件名>`,两份都叫 image.png 的素材会互相覆盖 ——
        # 而宿主按素材缓存着前一份的直链,那条链接从此下到的是另一份文件。同样的内容落在同一个键上,
        # 重传是幂等的。
        key = f"mosael/{storage.content_hash(path)[:16]}/{os.path.basename(path)}"
    bucket.upload_file(key, path, content_type=storage.content_type_of(path), reporter=reporter)
    return {
        "key": key,
        "url": bucket.presign(key, expires=expires),
        "public_url": bucket.public_url(key),
        "expires_in": expires,
        "summary": line(
            locale,
            f"已传到 {_where(bucket, key)},直链 {expires} 秒内有效",
            f"Uploaded to {_where(bucket, key)}; the link is valid for {expires}s",
        ),
    }


def presign(payload: dict, locale: str, reporter: Reporter) -> dict:
    key = str(payload.get("key") or "").strip().lstrip("/")
    if not key:
        raise StorageError(line(locale, "要给哪个对象签链接?", "Which object should I sign?"))
    bucket = _bucket(locale)
    expires = bucket.clamp_expires(payload.get("expires"))
    return {"key": key, "url": bucket.presign(key, expires=expires), "expires_in": expires,
            "summary": line(locale, f"{expires} 秒内有效的直链", f"A direct link valid for {expires}s")}


def fetch(payload: dict, locale: str, reporter: Reporter) -> dict:
    """把桶里的一个对象拉回素材库。

    **交回的是地址,不是字节** —— 让宿主去搬:进度、取消、重试、大小上限、失败隔离,
    它的任务机制里全都有,而插件这一侧只有一次短命的 stdio 调用(见 docs/PLUGIN_MANIFEST)。
    """
    key = str(payload.get("key") or "").strip().lstrip("/")
    if not key or key.endswith("/"):
        raise StorageError(line(locale, "要拉哪个对象?(给完整的对象路径,不是目录)",
                                "Which object should I fetch? (a full object key, not a folder)"))
    url = _bucket(locale).presign(key, expires=storage.DEFAULT_EXPIRES)
    return {"artifact": {"url": url, "filename": os.path.basename(key)},
            "summary": line(locale, f"已取回 {key}", f"Fetched {key}")}


def listing(payload: dict, locale: str, reporter: Reporter) -> dict:
    try:
        limit = int(payload.get("limit") or 100)
    except (TypeError, ValueError):
        limit = 100
    items, following = _bucket(locale).listing(
        str(payload.get("prefix") or ""), limit, str(payload.get("cursor") or ""))
    return {"items": items, "count": len(items), "next_cursor": following,
            "summary": line(locale, f"{len(items)} 个对象" + (",还有下一页" if following else ""),
                            f"{len(items)} objects" + ("; more on the next page" if following else ""))}


if __name__ == "__main__":
    storage.run(
        {"storage_upload": upload, "storage_presign": presign, "storage_fetch": fetch, "storage_list": listing},
        streaming=frozenset({"storage_upload"}),
    )
