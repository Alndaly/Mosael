# 百度网盘

把百度网盘里的素材拉进素材库。

## 能做什么

| 工具 | 干什么 |
| --- | --- |
| `pan_list` | 列一个目录下的文件和子目录,给出 `fs_id` |
| `pan_search` | 按文件名搜(递归),找不准路径时用它 |
| `pan_import` | 按 `fs_id` 把文件拉进素材库,返回 `asset_id` |

拿到 `asset_id` 之后它就是一份普通素材:插时间线、当生成的首帧、拿去发布,都一样。
`pan_import` 也是一个工作流节点(「从百度网盘导入」),输出 `asset_id` / `asset_name`。

## 不做什么

**不做上传。** 上传涉及分片、断点、秒传(要算文件 md5 和 slice-md5),是完全另一摊工作量;
而日常真正在做的事是「把网盘里的素材拉进来剪」。

## 配置

1. 去 [百度网盘开放平台](https://pan.baidu.com/union) 注册一个应用,拿到 AppKey / SecretKey
2. 走一次 OAuth 拿到 `refresh_token`(有效期 10 年)
3. 在 Open Studio 的插件页接入这个包,把这三样填进去

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
