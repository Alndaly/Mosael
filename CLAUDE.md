# Mosael repository instructions

## Understand current code

When `.codegraph/` exists, use `codegraph explore` (or its MCP equivalent) before text searches to locate or understand code. Recheck the current branch and local changes at the start of work; preserve updates made by other tools.

## Packaging and releases

When the user asks to build or publish a release, read [docs/RELEASING.md](docs/RELEASING.md) and [docs/MACOS_SIGNING.md](docs/MACOS_SIGNING.md) first. They document the actual GitHub Actions and local macOS notarization handoff, including the existing `mosael-release` Keychain profile. Use existing credentials without printing or exporting secrets. A release is complete only when the tested installers are verified and the authorized GitHub Release is published; pushing code or dispatching a workflow alone is not completion.

## UI 审美与自查(维护者 2026-10-21 追加)

**不要凭感觉加边框、加底色、加阴影。** 维护者的话:「参考一下 dribbble 上一些 UI 的审美 避免奇怪的设计」。
落地成几条可执行的:

- **一层结构只表达一件事**:外框只画一圈;里面要分组用**一条分隔线**或**一条左边条**,不再画第二圈框。
  (执行历史那块连改八次,根子就是四圈边三块底叠在一起 —— 见 ADR 0074。)
- **间距只用一套刻度**:段间 12 / 块间 8 / 行内 4。**出现第四个数就是错的**。
- **底色最多三档**:面板底、次级面(略浅/略深的同一色系)、选中态。别为每块区域单独调色。
- **动效与阴影只做"层级"的暗示**,不做装饰:浮窗有阴影是因为它浮着;停靠面板**不加**。
- **同一种控件在全仓同一个高度**(见 `frontend/src/components/ui` 的 scale 与 `design/` 下的棘轮)。

**自查方式**:改完 UI **自己截图看** —— 用 Computer Use(ADR 0075)或 `agent-browser` 都行,
**至少看两种宽度 + 深/浅色**,然后问一句"这块里有没有两条边在说同一件事"。
这一条写在这里是因为**维护者反复指出"看着怪"**,而"怪"几乎总是**同一语义被画了两遍**。

## UI 一致(同类页面用同一套东西)

维护者反复提的一条:**同类页面里,同一个动作要出现在同一个位置、用同一个形状、写同一种措辞**。改一处之前先看同类页里其余几个是怎么做的:

- **社区四个市场页**(`/community`、`/plugins`、`/workflows`、`/boards`):页头都走 `CommunityHeader` 的 `contribute`,右上角、胶囊形、和 `min-h-10` 同高;
  - 能上传的类型写「**分享你的工作流 / 画布 / 作品**」,指向 `/community/upload`;
  - **不能上传的(`/plugins`)指文档**是对的,措辞也随之不同(「写一个插件」)—— 那是另一件事,不是不一致;
- **一屏只出现一处同一个动作**(例如「去上传」):页头给了,列表工具条和空态就只写文字指路,不再放第二颗按钮;
- **按钮变体按语义挑**,不要凭手感:`default` 主作用、`outline` 并排的次要作用、`ghost` 工具栏/卡片角上、`inline` 挨着某个值的小动作(见 `components/ui/button.tsx` 的注释与 `design/` 下的棘轮);
- **列表页结构对齐**:页头 → 搜索条 → 卡片网格 → 空态;空态要么给「清除筛选」,要么指路到页头那颗按钮,不给第二种上传入口。

这一条是**主张**,不是 lint 能全兜住的:改完自己把同类页并排看一遍(或 `curl` 出来比对页头 CTA、搜索、空态)。

## 本地开发服务(用户就用它测)

用户在本机 `http://127.0.0.1:3100`(官网)和 `http://127.0.0.1:8000`(MosaelCloud)上测试。**每次任务或提交做完，跑一次 `scripts/dev-services.sh`** 把两个服务重建到当前 HEAD;只改了 `cloud/` 就 `scripts/dev-services.sh cloud`。不重建，用户看到的是上一个提交的行为，会被当成"改了没生效"(踩过)。密钥(126 SMTP、官方号密码)在 `~/.mosael-dev.env`，不进仓库。
