# R2 手工上传清单 · v2.3.0

维护者决定手工上传（本机上行约 0.6 MB/s，脚本的"传一遍 + 回读校验"要两倍时间）。
**以下是逐项核对过的清单**：3 个对象已在 R2 上（内容也已校验），其余 11 个文件 + 1 个生成页要传。

## 目标位置

| 项 | 值 |
| --- | --- |
| 服务 | Cloudflare R2 |
| Bucket | `mosael-releases` |
| 公开域名 | `https://dl.mosael.com` → 对象前缀 `mosael/` |
| 本地来源 | `dist/2.3.0/`（15 个文件，含 `SHA256SUMS`） |
| **排除** | 任何 `.*` 隐藏文件（例如 `baiduyun.uploading.cfg`，那是百度网盘客户端的临时文件） |

## ① `mosael/v2.3.0/` —— 不可变副本（**先传全这一层**）

已有 3 个（**不要重传**，已回读校验过）：`Mosael Setup 2.3.0.exe`(278,194,444)、
`Mosael Setup 2.3.0.exe.blockmap`(292,659)、`Mosael-2.3.0-arm64.dmg`(348,722,195)

还需传 **11 个文件**：

| 文件 | 字节 | sha256 前 16 位 |
| --- | --- | --- |
| `Mosael-2.3.0-mac-signed.zip` | 307,568,032 | `b348e659cafdcc97` |
| `Mosael-2.3.0-mac-signed.zip.blockmap` | 320,463 | `d0344d679fe9fdf8` |
| `SHA256SUMS` | 1,345 | `74156d4fa33c6253` |
| `latest-mac.yml` | 311 | `749d64a87f2cc136` |
| `latest.yml` | 301 | `61de0c53e277460f` |
| `registry.json` | 41,239 | `22916673c5bfc7ce` |
| `mosael-browser-extension.zip` | 4,623,280 | `25e48fca5532003d` |
| `dev.mosael.baidu-pan.zip` | 19,036 | `eb93eee6a91313f7` |
| `dev.mosael.blender.zip` | 16,348 | `24254877c689b2a2` |
| `dev.mosael.manim.zip` | 68,507 | `8c3f8012a75b5d90` |
| `dev.mosael.remotion.zip` | 36,536 | `9da5e85145da1e04` |
| `dev.mosael.text-toolkit.zip` | 11,671 | `b39eb95652992dbb` |
| `dev.mosael.tikhub.zip` | 5,684 | `e5557c96013f8abb` |

**缓存头**：全部 `public, max-age=31536000, immutable`。

## ② `mosael/latest/` —— 当前版指针（同名覆盖）

上传**上表 11 个 + 已在 R2 的 3 个 = 14 个**（`latest/` 里现在还是 2.2.3 / 2.2.4 的旧产物）。

**缓存头**：
- `latest-mac.yml`、`latest.yml`、`index.html` → `public, max-age=0, must-revalidate`
- 其余 → `public, max-age=31536000, immutable`

## ③ 删掉 `mosael/latest/` 里的 10 个旧对象

不删的话 `index.html` 与目录里会一直留着上一代的包（R2 没有"替换目录"）：

```
Mosael Setup 2.2.3.exe            Mosael Setup 2.2.4.exe
Mosael Setup 2.2.3.exe.blockmap   Mosael Setup 2.2.4.exe.blockmap
Mosael-2.2.3-arm64.dmg            Mosael-2.2.4-arm64.dmg
Mosael-2.2.3-mac-signed.zip       Mosael-2.2.4-mac-signed.zip
Mosael-2.2.3-mac-signed.zip.blockmap   Mosael-2.2.4-mac-signed.zip.blockmap
```

## ④ 两个 `index.html` 由我生成

`mosael/v2.3.0/index.html` 与 `mosael/latest/index.html` 是脚本按"目录里真实存在的文件"渲染的下载页，
**不要手抄**。你传完文件后我跑 `renderDownloadPage` 生成并上传。

## 传完通知我，我立刻做

1. 生成并上传两个 `index.html`；
2. **逐个对象回读** Size + SHA-256（对照上表的完整值，不只是前 16 位）；
3. 抽查公网 `https://dl.mosael.com/mosael/latest/latest-mac.yml` 是否为 `2.3.0`；
4. 改官网默认下载渠道（境内外默认 R2、GitHub / 百度兜底）+ 官网 182 项测试 + 提交；
5. 更新 `docs/validation/2026-10-29-release-2.3.0.md`。
