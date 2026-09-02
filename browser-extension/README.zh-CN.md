# Open Studio Chrome 扩展

[English](README.md) | **简体中文**

这个扩展把 Open Studio 的视频辅助能力放进 Chrome 原生 Side Panel。它不会向页面插入浮动窗口，
切换标签页时侧栏会跟随当前视频。

## 功能

- 读取 YouTube 与 B 站已有字幕并显示为逐字稿；Pornhub 等站点无结构化字幕时可交给 Open Studio 自动下载并转写。
- Open Studio 转写保留逐词时间戳，可点击任意词精确跳转；站点字幕或旧数据则按可用的句级时间跳转。
- 原文与第二语言并排显示为双语字幕，搜索同时匹配两行内容。
- 第二语言优先读取站点现有字幕或 YouTube 翻译轨；没有可用轨道时再调用 Open Studio 翻译。
- 一键把当前视频链接提交到 Open Studio 素材库。
- 只提取播放器当前视频帧（不包含播放按钮等 HTML 控件）并作为 PNG 素材入库。
- 选择目标工作区和可选项目。
- 界面支持跟随 Chrome 语言，也可在设置中固定为简体中文或 English。

## 安装

### 从 Release 安装

下载 GitHub Release 中的 `open-studio-browser-extension.zip` 并解压，然后：

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

1. 启动 Open Studio，确认本机后端运行在 `http://127.0.0.1:8800`。
2. 在 Chrome 打开 YouTube、B 站或 Pornhub 视频页，点击扩展图标打开右侧 Side Panel。
3. 站点已有的逐字稿与第二字幕轨无需登录 Open Studio 即可使用。
4. 首次自动转写、AI 翻译、导入或截帧时，点侧栏右上角设置，用 Open Studio 账号登录并选择素材工作区。
5. 界面语言默认跟随 Chrome；需要固定语言时，在同一设置页选择「简体中文」或「English」。

密码只用于调用 `/api/auth/login` 换取会话，不写入 `chrome.storage`；扩展只保存返回的会话、后端地址
和素材目标。可以随时在设置中断开连接并删除本地会话。

## 权限

| 权限 | 用途 |
| --- | --- |
| `sidePanel` | 打开 Chrome 原生右侧栏 |
| `tabs` | 跟随活动标签页并向当前视频页发送跳转命令 |
| `activeTab` | 截取用户当前可见的视频画面 |
| 可选的 `<all_urls>` | 首次点击“截取当前帧”时按需请求，用于 Chrome 截图 API；安装时不授予 |
| `storage` | 保存 Open Studio 会话与目标工作区 |
| YouTube 域名族（含 `youtu.be`、`youtube-nocookie.com`、`googlevideo.com`、`ytimg.com`） | 覆盖视频页、短链、嵌入页及官方媒体资源 |
| B 站域名族（含 `hdslb.com`、`bilivideo.com`、`bilivideo.cn`） | 覆盖视频页、字幕文件及官方媒体资源；字幕由扩展后台获取，避免网页翻译或 CORS 干扰 |
| Pornhub 页面域名 | 识别视频页、同步 HTML5 播放时间、跳转句子、截帧与提交链接；站点未提供结构化字幕时回退到 Open Studio 转写 |
| `127.0.0.1` / `localhost` host permission | 调用本机 Open Studio API |

扩展不会申请 `cookies` 权限，也不会把浏览器登录态导出给 Open Studio。会员、私享或地区受限视频的
逐字稿可使用当前网页本身已有的字幕权限，但**视频导入**仍由 Open Studio 后端下载；这类内容需要在
Open Studio 的浏览器池中选择对应登录身份后从应用内导入。

B 站字幕地址带有临时签名。扩展每次进入视频都会按当前 `bvid` / `cid` 重新读取字幕清单，不复用页面中
可能已经过期的地址；字幕网络请求由后台在严格限定的官方接口与字幕路径中完成。

域名权限覆盖完整资源域名族，但后台网络代理仍只允许当前适配器需要的字幕 API 与字幕文件路径。
Pornhub 当前播放器使用 blob 媒体源且不暴露结构化字幕轨，适配器会选择页面中真正可见、可播放的主视频，
避免被隐藏广告或占位 `<video>` 干扰；逐字稿使用 Open Studio 回退生成。

## 无字幕时自动转写

站点没有返回字幕时，侧栏会显示「使用 Open Studio 生成逐字稿」。点击后按已有后端流程执行：链接下载
入库、启动语音识别、轮询后台任务，完成后把带时间码的结果直接放回侧栏。生成结果仍支持播放跟随、
逐词点击跳转、搜索和双语字幕。侧栏保留后端返回的逐词时间戳，同时按句末标点、停顿、时长和可读长度
整理成易读的逐字稿行；点击行内任意词会跳到该词的时间。旧转写没有逐词时间戳时按句子切分并使用句级
跳转，不会直接显示整段字幕。下载和识别是后台任务，
长视频所需时间取决于网络与已选择的转写引擎。

再次进入同一视频时，扩展会先按稳定的视频身份查询当前工作区已有的完成态逐字稿并直接恢复，不会重复
下载或转写。新 URL 导入会把来源身份写入素材元数据；升级前已经生成的记录则从历史 URL 导入任务反查，
因此无需手动迁移。YouTube 分享链接、Pornhub 语言子域名和常见跟踪参数不会把同一视频拆成多份身份。

## 已知限制

- 仅支持 Chrome 116+ 的 Manifest V3 Side Panel；Edge 可能兼容，但当前不作为验证目标。
- Open Studio 自动转写需要本机后端在线、账户已连接，并且后端能够下载当前链接。
- 截帧优先从 `<video>` 解码画面直接导出；跨域媒体禁止 Canvas 导出时，会暂时隐藏播放器 HTML 覆盖层后
  只裁切视频矩形。播放器完全滚出视口时会拒绝兼容捕获。
- 后端连接目标仅限 `localhost` / `127.0.0.1`；跨域截帧兼容路径首次使用时会请求可选的网页截图权限。

## 开发与验证

```bash
pnpm --dir browser-extension test
pnpm --dir browser-extension typecheck
pnpm --dir browser-extension build
```

侧栏使用 React、Tailwind CSS v4 与扩展内自有的 shadcn/ui 组件；功能层不直接使用原生表单控件，也不维护
旧式手写 class 样式表。构建脚本把 `src/background.ts`、`src/content.ts`、`src/page-bridge.ts` 和
`src/sidepanel.tsx` 分别打包，编译 `src/styles.css` 中的 Tailwind 主题，并把 manifest、`_locales`、HTML
和图标写入 `dist/`。扩展版本由根 `package.json` 注入，与桌面版本一致。
