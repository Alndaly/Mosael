# ADR 0073:ComfyUI 的版本供给链 —— 运行时查上游最新 release,换到它的 tag;钉死表退为离线降级,sha256 下载后记录

## Status

Accepted — 2026-10-18。修订 **ADR 0041 §4「更新、回滚」**(那一轮把版本来源定为插件里一张钉死的表)。
判据由 `backend/tests/test_comfyui_plugin_managed.py` 的「查上游最新 / 升到上游最新」那一组、宿主侧的
`backend/tests/test_local_service_install.py`(换版本、试起失败回滚、查不到不说已最新)和
`frontend/src/features/plugins/LocalServiceVersion.dom.test.tsx`(中英三种状态)守着。

## Context

ComfyUI 的「更新」此前**只认插件里钉死的一张表**(`plugins/bundled/comfyui/tools/managed.py` 的
`COMFYUI_PINNED`:0.38.0、0.39.0,官方 GitHub tag 压缩包 + 写死的 sha256)。这条链有它的好:升级过程不依赖
网上的元数据,压缩包内容按 sha256 逐字节校验,下载源被镜像 / 代理换了内容也装不上。

但它有一个**会对人撒谎**的地方:

- `service_versions` 交回的 `latest` 是**表里最新那个**,`update` 是「表里比装着的新一个」;
- 界面据此写「装着的是 {current},**已经是最新的**」—— 而维护者理解的是**上游最新**。上游实际已经到
  0.41.0(2026-10-18 实测)时,界面还指着 0.39.0 说「已最新」;
- 上游发新版之后,要等 Mosael 发一版插件、更新表、再发一版应用,用户那边的「更新」才看得见新版本;
- 表里的 sha256 事先不知道上游 tag,所以「换到上游最新」这条需求**不可能**沿用「先校验再解」的顺序 ——
  这不是实现细节,是供给链本身的取舍,要记下来。

## Decision

### 1. 上游最新从 GitHub 的 releases API 查

插件新增 `tools/upstream.py`,用
`https://api.github.com/repos/comfyanonymous/ComfyUI/releases/latest` **运行时**查:

- 带 `Accept: application/vnd.github+json`、`X-GitHub-Api-Version` 和 `User-Agent`(GitHub API 会拒绝没有
  UA 的请求);8 秒超时,不让「版本」那一行一直转;
- 只收 `v0.41.0` / `0.41.0` 这种 tag(正则 `^v?(\d+(?:\.\d+)+)$`),版本号 = 去掉 `v` 的 tag;
- 发布说明只取前 5 条 bullet、去掉 Markdown 链接和「by @谁 in …」的尾巴,最多 600 字(原文不翻译);
- **只走官方主机**:`pinned.OFFICIAL_HOSTS`(`api.github.com`、`codeload.github.com`、`github.com`、
  `objects.githubusercontent.com`);跳转也只许落在这几个里面 —— 仓库改过名,旧地址会 301 到
  `api.github.com/repositories/<id>/…`,这个 301 是官方主机之间的,照走;任何跳到别处的 302/301 一律不收;
- 状态只有五种(加上「这次没查」):`ok`、`offline`、`rate_limited`(403/429;未认证一小时 60 次)、
  `not_found`(404)、`error`(回答不是 JSON、tag 认不出、状态不是 200)。**后四种都把版本留空、给一句
  按读的人的语言说的原因**;调用方据此退回钉死表 —— 查不到**绝不**等于「已经是最新的」。

`service_versions` 多带一个 `check_upstream: true` 才联网:旧调用(直接跑插件、其他宿主版本)照旧只读
安装记录,测试也就不用为了读版本去连网(测试注入 `fetch` 替身,绝不真连 GitHub)。

### 2. 换版本的目标从「表里的下一个」扩展为「上游最新的 tag」

- `versions` 里有可升的上游版本时,`update` 是它、`source` 是 `upstream`;上游查不到(或表里有更新的)时
  `update` 退回表里的下一个、`source` 是 `pinned`。钉死表**保留**为离线 / 降级路径;
- `service_update` 多收一个 `tag`(宿主把刚查到的 `v0.41.0` 原样交回);插件只接受
  `v<版本号>` 且与版本号对得上的 tag,否则不放行。没有 tag 的陌生版本照旧拒绝;
- 源码包**只从官方 codeload 下**:
  `https://codeload.github.com/comfyanonymous/ComfyUI/tar.gz/refs/tags/<tag>`;上游这一条**不接**
  「管理 → 下载源」里的 GitHub 镜像前缀(钉死表那一条照旧可以接);
- **sha256 事先不知道** —— 上游 tag 在发版前并不存在,插件里不可能有它的哈希。所以下载时边下边算,
  **下完把算出来的 sha256、tag、地址、时间记进安装记录**(`mosael-install.json` 的 `source`),日志里也写一行;
  钉死表那一条仍然**先校验再解**。回滚到上一版时这份记录跟着作废(别让记录说装着的是被换下来的那一版);
- 其余安全机制**一条都没动**:新源码解到旁边(`ComfyUI.next`)、先 `pip freeze`、改名切换、五样用户数据
  (`models` / `custom_nodes` / `user` / `input` / `output`)搬过去、`--no-deps` 按 freeze 装回、试起 +
  `/system_stats` 健康检查、不通过自动换回、可取消、可回滚到上一版;解包仍然只收普通文件和目录
  (链接、绝对路径、`..` 不收),个数 / 总大小有上限。

### 3. 界面把四件事摆出来,并且不说谎

「版本」那一行显示 **当前 / 上游最新 / 上次检查 / 可升**:

- 当前 == 上游最新 → 才说「装着的是 x,和上游最新一致」;
- 当前 < 上游最新 → 说「上游最新是 y」,按钮「更新到 y」;
- 上游查不到、表里有更新 → 说「查不到上游最新」并给原因,按钮照给(升到内置的 x)—— 这是离线降级;
- 上游查不到、表里也没有更新 → 说「查不到上游最新」,外加一条「这不是『已经是最新的』」;**不出现**已最新。

中英各一套文案;`upstream.status` 不是 `ok` 时界面明确写出「网络 / 离线 / 限流 / 查不到」的原因。
查询失败时 `begin_update` 的拒绝也得说查不到(新的 `localServiceErr_noUpdateUnknown`)—— 只有上游真的就是
装着的那个版本时,才说「已经是最新的」。

## 失去什么,怎么缓解

- **失去了「下载前就知道内容」**:上游包下完才知道 sha256,一个被 TLS 或代理换掉的压缩包在下完之前拦不住。
  缓解:只走官方 GitHub + 跳转白名单(不接任意镜像)、TLS、下载大小上限、解包仍然有边界和数量上限、
  下完记录 sha256 可事后追溯、仍然要试起通过才算换好、换好了仍可一步回滚。钉死表那一条路径保持先校验。
- **失去了「离线也能判断有没有新版」**:离线时只能退回表里的下一个,并明说「查不到」。这是有意的 ——
  宁可说查不到,也不猜一个「已最新」。
- **多了一次网络调用**:`service_versions` 每次打开连接页会问一次 GitHub(未认证 60 次/小时)。8 秒超时、
  不自动重试;限流时明说原因,界面仍然可用(钉死表兜底)。这一版没做磁盘缓存:版本行需要的是「此刻的上游」,
  缓存会把「上次检查」变成一句更旧的话;如果实测发现频繁打开页面撞限流,再加短 TTL 缓存,而不是把它藏起来。
- **上游 tag 与源码包内容不一定和「release 正文」对应**:正文只是展示。

## Alternatives

- **把钉死表改成每次启动自动更新**:仍然是「后台悄悄换表」,离线 / 限流时的行为更难说清,且改变了
  「钉死的包按 sha256 校验」这条;不取。
- **只在设置页提供一个「检查更新」按钮**:版本行仍然会说「已最新」,维护者看到的那句假话没消失;不取。
- **查上游 API 的 tags 端点自己挑最大 semver**:releases/latest 已经是 GitHub 维护的「最新 release」,
  还带发布说明;tags 端点会把预发布、非 semver tag 一起算进来;不取。
- **把上游 tag 的 sha256 在下载后写回插件里的表**:插件包是只读的、下次升级会覆盖;记录写在安装目录的
  安装记录里,才是「这一份装的是什么」的事实来源。

## Evidence

- 真实调用(2026-10-18,`curl -sSL -H "Accept: application/vnd.github+json"`):
  `tag_name = "v0.41.0"`,`html_url = https://github.com/Comfy-Org/ComfyUI/releases/tag/v0.41.0`,
  `published_at = 2026-10-15T22:57:45Z`;`codeload.github.com/comfyanonymous/ComfyUI/tar.gz/refs/tags/v0.41.0`
  下到 12,733,863 字节,sha256 `31189259d1e2d468f4859d35236edb80c245774bdb2aa33734661a0713330060`
  (只作为实测记录,不写进插件 —— 上游下一个 tag 就变了)。
- 测试里一次都不连网:releases 回答和源码包都由 `fetch` 替身 / 本地文件注入;升级在临时目录里做,
  五样用户数据快照逐字节比对。
- 真机清单(Windows / Linux 的 CUDA 路径、`/system_stats` 试起、回滚)仍是「待跑」——这一版没在真机上验。
