# Mosael Chrome 扩展

[English](README.md) | **简体中文**

这个扩展把 Mosael 的视频辅助能力放进 Chrome 原生 Side Panel。它不会向页面插入浮动窗口，
切换标签页时侧栏会跟随当前视频。

## 功能

- 支持当前安装的 yt-dlp 能识别的视频链接；YouTube 与 B 站优先读取原生字幕，其余站点可交给 Mosael 自动下载并转写。
- Mosael 转写保留逐词时间戳，可点击任意词精确跳转；站点字幕或旧数据则按可用的句级时间跳转。
- 原文与第二语言并排显示为双语字幕，搜索同时匹配两行内容。
- 第二语言优先读取站点现有字幕或 YouTube 翻译轨；没有可用轨道时再调用 Mosael 翻译。
- 一键把当前视频链接提交到 Mosael 素材库。
- 只提取播放器当前视频帧（不包含播放按钮等 HTML 控件）并作为 PNG 素材入库。
- 选择目标工作区、可选项目和可选的 Mosael 浏览器池登录身份。
- 界面支持跟随 Chrome 语言，也可在设置中固定为简体中文或 English。

## 安装

### 从 Release 安装

下载 GitHub Release 中的 `mosael-browser-extension.zip` 并解压，然后：

1. 打开 `chrome://extensions`。
2. 打开右上角「开发者模式」。
3. 点击「加载已解压的扩展程序」，选择解压后的目录。
4. 把扩展固定到工具栏。

### 从源码构建

```bash
pnpm install
pnpm build:extension
```

在 `chrome://extensions` 中加载 `browser-extension/dist/`。

## 使用

1. 启动 Mosael，确认本机后端运行在 `http://127.0.0.1:8800`。
2. 在 Chrome 打开 yt-dlp 能识别的视频链接，点击扩展图标打开右侧 Side Panel。
3. 站点已有的逐字稿与第二字幕轨无需登录 Mosael 即可使用。
4. 首次自动转写、AI 翻译、导入或截帧时，点侧栏右上角设置，用 Mosael 账号登录并选择素材工作区。
   会员、私享、地区受限或触发站点风控的内容，还可选择已在 Mosael 浏览器池中登录并配置代理的身份。
5. 界面语言默认跟随 Chrome；需要固定语言时，在同一设置页选择「简体中文」或「English」。

密码只用于调用 `/api/auth/login` 换取会话，不写入 `chrome.storage`；扩展只保存返回的会话、后端地址
和素材目标。可以随时在设置中断开连接并删除本地会话。

## 权限

| 权限 | 用途 |
| --- | --- |
| `sidePanel` | 打开 Chrome 原生右侧栏 |
| `tabs` | 跟随活动标签页并向当前视频页发送跳转命令 |
| `activeTab` | 截取用户当前可见的视频画面 |
| `<all_urls>` | 在任意 HTTP(S) 视频页发现 HTML5 播放器，并在 Canvas 受跨域限制时执行纯视频区域兼容捕获 |
| `storage` | 保存 Mosael 会话与目标工作区 |
| `127.0.0.1` / `localhost` host permission | 调用本机 Mosael API |

扩展不会申请 `cookies` 权限，也不会读取或导出 Chrome 登录态。侧栏可选择 Mosael 已管理的浏览器池
身份，并只把身份 ID 交给后端；下载任务由后端通过既有浏览器池复用该身份的 Cookie 与代理。

B 站字幕地址带有临时签名。扩展每次进入视频都会按当前 `bvid` / `cid` 重新读取字幕清单，不复用页面中
可能已经过期的地址；字幕网络请求由后台在严格限定的官方接口与字幕路径中完成。

YouTube / B 站的后台网络代理仍只允许适配器需要的官方字幕 API 与字幕文件路径，不会因为 `<all_urls>`
而变成任意网络代理。其他页面只做 DOM 播放器发现；是否能导入由后端当前安装的 yt-dlp extractor 注册表
判断。通用适配器会选择页面中真正可见、可播放的主视频，避免被隐藏广告或占位 `<video>` 干扰。

## 无字幕时自动转写

站点没有返回字幕时，侧栏会显示「使用 Mosael 生成逐字稿」。点击后按已有后端流程执行：链接下载
入库、启动语音识别、轮询后台任务，完成后把带时间码的结果直接放回侧栏。生成结果仍支持播放跟随、
逐词点击跳转、搜索和双语字幕。侧栏保留后端返回的逐词时间戳，同时按句末标点、停顿、时长和可读长度
整理成易读的逐字稿行；点击行内任意词会跳到该词的时间。旧转写没有逐词时间戳时按句子切分并使用句级
跳转，不会直接显示整段字幕。下载和识别是后台任务，
长视频所需时间取决于网络与已选择的转写引擎。

再次进入同一视频时，扩展会先按稳定的视频身份查询当前工作区已有的完成态逐字稿并直接恢复，不会重复
下载或转写。新 URL 导入会把来源身份写入素材元数据；升级前已经生成的记录则从历史 URL 导入任务反查，
因此无需手动迁移。来源 URL 会去除常见跟踪参数和片段，避免把同一视频拆成多份身份。

## 已知限制

- 仅支持 Chrome 116+ 的 Manifest V3 Side Panel；Edge 可能兼容，但当前不作为验证目标。
- Mosael 自动转写需要本机后端在线、账户已连接，并且当前安装的 yt-dlp 能下载链接。登录、地区或
  风控限制需要选择匹配的浏览器池身份或代理，DRM 内容仍无法下载。
- 「可导入/可转写」与「网页内可控制」是独立能力。自定义播放器、跨域 iframe 或 DRM 播放器即使能被
  yt-dlp 识别，也可能没有可用的页面 `<video>`；此时仍可导入和转写，但时间跳转与截帧会禁用。
- 截帧优先从 `<video>` 解码画面直接导出；跨域媒体禁止 Canvas 导出时，会暂时隐藏播放器 HTML 覆盖层后
  只裁切视频矩形。播放器完全滚出视口时会拒绝兼容捕获。
- 后端连接目标仅限 `localhost` / `127.0.0.1`。

## 开发与验证

```bash
pnpm --dir browser-extension test
pnpm --dir browser-extension typecheck
pnpm --dir browser-extension build
cd backend && uv run pytest tests/test_url_import.py
```

后端测试会对 yt-dlp 自带的全部 canonical HTTP(S) extractor 样例执行无网络合约检查；真实站点抽样仍会
受到测试机器的登录状态、IP、地区与站点风控影响，失败应区分访问受限和适配器回归。

侧栏使用 React、Tailwind CSS v4 与扩展内自有的 shadcn/ui 组件；功能层不直接使用原生表单控件，也不维护
旧式手写 class 样式表。构建脚本把 `src/background.ts`、`src/content.ts`、`src/page-bridge.ts` 和
`src/sidepanel.tsx` 分别打包，编译 `src/styles.css` 中的 Tailwind 主题，并把 manifest、`_locales`、HTML
和图标写入 `dist/`。扩展版本由根 `package.json` 注入，与桌面版本一致。
