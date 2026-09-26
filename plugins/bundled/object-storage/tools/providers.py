"""各家对象存储的**差异**,就这一张表。

HTTP 接口是同一套(PUT/GET 对象、分片上传、列目录、XML 错误体),不同的只有这几格:签名方言、
默认接入点怎么拼、预签名最长能签多久、用不用路径式寻址、列目录用 V1 还是 V2。它们全写在这里,
主体(storage.py)一行都不认识「阿里云」。

每一格都对过官方实现或文档(测试里的向量来自各家官方 SDK):

- 阿里云 OSS:原生 V4(`OSS4-HMAC-SHA256`),`oss-<地域>.aliyuncs.com`;预签名最长 7 天
  (alibabacloud-oss-v2 的 presigner 超过 7 天直接拒)。https://help.aliyun.com/zh/oss/developer-reference/recommend-to-use-signature-version-4
- 腾讯云 COS:原生 `q-sign-algorithm=sha1`,`cos.<地域>.myqcloud.com`;KeyTime 由调用方定,文档没有上限;
  列目录只有 V1(GET Bucket)。https://cloud.tencent.com/document/product/436/7778
- 火山引擎 TOS:`TOS4-HMAC-SHA256`,`tos-<地域>.volces.com`;预签名 1~604800 秒(官方 SDK `tos` 的校验);
  **原生接口的正文是 JSON**(列目录、分片上传、错误体),不是 XML。
- Amazon S3:SigV4,`s3.<地域>.amazonaws.com`;`X-Amz-Expires` 最长 604800 秒。
  https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
- S3 兼容服务(MinIO、Cloudflare R2、Ceph……):同一套 SigV4,**接入点必填**、走**路径式**寻址
  (`<接入点>/<桶>/<对象>`)—— 自建服务多半没有给每个桶配泛域名,虚拟主机式寻址连不上;
  接入点可以带 `http://`(本机的 MinIO 常常没有证书)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import qsign
import sigv4

#: SigV4 系预签名的上限(7 天)。三家(S3 / OSS / TOS)是同一个数。
SEVEN_DAYS = 7 * 24 * 3600


@dataclass(frozen=True)
class Provider:
    id: str
    #: 摘要里 `oss://桶/对象` 那一段的协议名。
    scheme: str
    #: 签名方言(见 storage.Bucket 的约定)。
    dialect: object
    #: 地域 → 默认接入点主机名。None = 没有默认,接入点必填。
    endpoint_for: Callable[[str], str] | None
    #: 预签名最长多少秒。None = 官方没有上限。
    max_expires: int | None
    #: 路径式寻址(桶在路径里而不是域名里)。
    path_style: bool = False
    #: 正文是 JSON 而不是 XML(列目录、分片、错误体)。火山 TOS 的原生接口就是这样 —— 官方 SDK `tos`
    #: 用 json.loads 读列目录、用 json.dumps 发 CompleteMultipartUpload。
    json_api: bool = False


PROVIDERS: dict[str, Provider] = {
    one.id: one
    for one in (
        Provider("aliyun-oss", "oss", sigv4.OSS, lambda region: f"oss-{region}.aliyuncs.com", SEVEN_DAYS),
        Provider("tencent-cos", "cos", qsign.COS, lambda region: f"cos.{region}.myqcloud.com", None),
        Provider("volcengine-tos", "tos", sigv4.TOS, lambda region: f"tos-{region}.volces.com", SEVEN_DAYS,
                 json_api=True),
        Provider("aws-s3", "s3", sigv4.AWS, lambda region: f"s3.{region}.amazonaws.com", SEVEN_DAYS),
        Provider("s3-compatible", "s3", sigv4.AWS, None, SEVEN_DAYS, path_style=True),
    )
}
