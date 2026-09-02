# 百度网盘

把百度网盘里的素材拉进素材库。

## 能做什么

| 工具 | 干什么 |
| --- | --- |
| `pan_list` | 列一个目录下的文件和子目录,给出 `fs_id` |
| `pan_search` | 按文件名搜(递归),找不准路径时用它 |
| `pan_import` | 按 `fs_id` 把文件拉进素材库,返回 `asset_id` |
| `pan_upload` | 把素材库里的一个文件传到网盘,返回 `fs_id` |

拿到 `asset_id` 之后它就是一份普通素材:插时间线、当生成的首帧、拿去发布,都一样。
`pan_import` 和 `pan_upload` 也都是工作流节点(「从百度网盘导入」/「上传到百度网盘」)。

## 上传是怎么走的

百度的上传协议本身就是三步,不是这里绕远:

1. **precreate** —— 报上文件大小和每个分片的 md5,拿一个 uploadid。
   **秒传在这一步发生**:百度认得这些 md5 就直接给结果,一个字节都不用传。
2. **superfile2** —— 逐片传。分片固定 4MB(百度规定的,不是可调参数 —— 换个数字
   precreate 报的 md5 清单就对不上)。
3. **create** —— 报上 uploadid 和分片清单,文件才算落地。

少一步都不行:只传不 create 的话,文件在网盘上根本不存在,而 superfile2 全都返回成功。

**默认不覆盖** —— 同名文件已存在时另存为副本。传错一次就把人家网盘上的东西冲掉,
这个代价比多一个副本大得多。要覆盖就显式传 `overwrite: true`。

md5 是流式算的,不整个载进内存 —— 上传的常常是几个 G 的成片。

## 插件怎么拿到那个文件

`pan_upload` 的 `asset_id` 在清单里标了 `"format": "asset"`,所以**宿主交过来的已经是一个
本地路径**(见 [PLUGIN_MANIFEST.md](../../../docs/PLUGIN_MANIFEST.md) 的「要收一个文件」)。
插件这一侧不知道素材库存在,也不需要知道。

给的是副本不是原件,调用结束即删。

## 配置

1. 去 [百度网盘开放平台](https://pan.baidu.com/union) 注册一个应用,拿到 AppKey / SecretKey
2. 走一次 OAuth 拿到 `refresh_token`(有效期 10 年)
3. 在 Mosael 的插件页接入这个包,把这三样填进去

「Access Token」那一栏**留空即可** —— 插件会用 refresh_token 自己换。

可选:填「起始目录」,`pan_list` 不带路径时就从那儿开始。

### token 自己续

百度的 `access_token` 三十天到期。插件撞上「过期」那个 errno 就换一个新的、原样重试一次,
并把换来的 token 交回宿主记住(靠 [`state` 通道](../../../docs/PLUGIN_MANIFEST.md))。
你填一次 refresh_token 就不用再管。

**access_token 和 refresh_token 都会被记住** —— 百度换 token 时会连 refresh_token 一起
轮换,只存前者的话,三十天后拿着一个已经作废的去换,得到的是一个查不出原因的失败。

续了一次还是过期,说明问题不在有效期上(AppKey 不对、应用被停用),这时才会报到界面上,
并且**只重试一次** —— 再试就是拿同一个错误刷接口。

## 它为什么不自己下载文件

`pan_import` 只换到 dlink 就交给宿主(见 [PLUGIN_MANIFEST.md](../../../docs/PLUGIN_MANIFEST.md)
的 artifact 那节)。理由不是省事:

- 插件这一侧只有**一次 60 秒的 stdio 调用** —— 自己下一个 2GB 的文件必然超时
- 就算不超时,用户看不到任何进度,按取消也停不下来
- 进度、重试、大小上限、失败隔离,宿主的任务机制里全都有

dlink 恰好是**必须带凭据才能下**的那种地址:不带 `User-Agent: pan.baidu.com` 直接 403,
还要把 `access_token` 拼在 url 上。所以交出去的不只是 url,还有那组请求头 —— 这也正是
artifact 通道支持 `headers` 的原因。

## 状态

接口形状按开放平台文档写,离线部分(参数拼装、分页、errno 翻译、artifact 交接)有测试覆盖。
**尚未对着真实账号跑过** —— 第一次接上真号时请核对一遍 `pan_list` / `filemetas` 的返回字段。
