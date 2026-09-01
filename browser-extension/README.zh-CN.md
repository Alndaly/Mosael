# Open Studio Chrome 扩展

[English](README.md) | **简体中文**

这个扩展把 Open Studio 的视频辅助能力放进 Chrome 原生 Side Panel。它不会向页面插入浮动窗口，
切换标签页时侧栏会跟随当前视频。

## 功能

- 读取 YouTube 与 B 站已有字幕并显示为逐字稿。
- 点击任意句子跳转到对应时间点，播放时自动标记当前句。
- 搜索逐字稿，并一键翻译为中文、英文、日文、韩文、法文、德文或西班牙文。
- 一键把当前视频链接提交到 Open Studio 素材库。
- 截取播放器当前可见画面并作为 PNG 素材入库。
- 选择目标工作区和可选项目。

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
3. 逐字稿本身无需登录 Open Studio 即可使用。
4. 首次翻译、导入或截帧时，点侧栏右上角设置，用 Open Studio 账号登录并选择素材工作区。

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

## 已知限制

- 仅支持 Chrome 116+ 的 Manifest V3 Side Panel；Edge 可能兼容，但当前不作为验证目标。
- 逐字稿依赖站点已有字幕。没有字幕的视频请先导入 Open Studio，再运行语音转写。
- 截帧按播放器当前可见区域裁切；播放器完全滚出视口时会拒绝操作。
- 当前连接目标为本机 `localhost` / `127.0.0.1` 后端，避免请求宽泛的网站访问权限。

## 开发与验证

```bash
pnpm --dir browser-extension test
pnpm --dir browser-extension typecheck
pnpm --dir browser-extension build
```

构建脚本把 `src/background.ts`、`src/content.ts`、`src/page-bridge.ts` 和 `src/sidepanel.ts` 分别打包，
再把 manifest、样式、HTML 和图标复制到 `dist/`。扩展版本由根 `package.json` 注入，与桌面版本一致。
