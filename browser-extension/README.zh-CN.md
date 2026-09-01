# Open Studio Chrome 扩展

[English](README.md) | **简体中文**

这个扩展把 Open Studio 的视频辅助能力放进 Chrome 原生 Side Panel。它不会向页面插入浮动窗口，
切换标签页时侧栏会跟随当前视频。

## 功能

- 读取 YouTube 与 B 站已有字幕并显示为逐字稿；站点无字幕时可交给 Open Studio 自动下载并转写。
- 点击任意句子跳转到对应时间点，播放时自动标记并滚动到当前句。
- 原文与第二语言并排显示为双语字幕，搜索同时匹配两行内容。
- 第二语言优先读取站点现有字幕或 YouTube 翻译轨；没有可用轨道时再调用 Open Studio 翻译。
- 一键把当前视频链接提交到 Open Studio 素材库。
- 截取播放器当前可见画面并作为 PNG 素材入库。
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
2. 在 Chrome 打开 YouTube 或 B 站视频页，点击扩展图标打开右侧 Side Panel。
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
| `storage` | 保存 Open Studio 会话与目标工作区 |
| YouTube / B 站 host permission | 读取当前视频的公开播放器与字幕信息 |
| `127.0.0.1` / `localhost` host permission | 调用本机 Open Studio API |

扩展不会申请 `cookies` 权限，也不会把浏览器登录态导出给 Open Studio。会员、私享或地区受限视频的
逐字稿可使用当前网页本身已有的字幕权限，但**视频导入**仍由 Open Studio 后端下载；这类内容需要在
Open Studio 的浏览器池中选择对应登录身份后从应用内导入。

## 无字幕时自动转写

站点没有返回字幕时，侧栏会显示「使用 Open Studio 生成逐字稿」。点击后按已有后端流程执行：链接下载
入库、启动语音识别、轮询后台任务，完成后把带时间码的结果直接放回侧栏。生成结果仍支持播放跟随、
点击跳转、搜索和双语字幕。下载和识别是后台任务，长视频所需时间取决于网络与已选择的转写引擎。

## 已知限制

- 仅支持 Chrome 116+ 的 Manifest V3 Side Panel；Edge 可能兼容，但当前不作为验证目标。
- Open Studio 自动转写需要本机后端在线、账户已连接，并且后端能够下载当前链接。
- 截帧按播放器当前可见区域裁切；播放器完全滚出视口时会拒绝操作。
- 当前连接目标为本机 `localhost` / `127.0.0.1` 后端，避免请求宽泛的网站访问权限。

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
