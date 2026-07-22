---
title: 下载与安装
description: 系统要求、运行方式、数据放在哪。
---

Mibu 是本地优先的桌面应用:剪辑、导出、工作流全程可离线;AI 能力(大模型 / 配音 / 生成)需在设置里配好各自的 API Key。

## 系统要求

| 平台 | 说明 |
| --- | --- |
| macOS | Apple Silicon(M 系列) |
| Windows | Windows 10 / 11(x64) |

- 内置后端引擎与 ffmpeg,开箱即用。
- 本地转写 / 声音克隆模型首次使用时按需下载(数百 MB 至数 GB),建议预留 **10GB+** 磁盘。

## 从源码运行(开发)

仓库根目录:

```bash
pnpm install
pnpm dev          # 起后端 + 前端 + Electron
```

打包桌面版:

```bash
pnpm build:backend      # PyInstaller 打后端
pnpm build:publisher    # 打发布执行器 bundle
pnpm --dir frontend build
pnpm dist               # electron-builder 出 mac/win 安装包
```

## 数据在哪

所有数据(账号 / 项目 / 素材 / 配置)都在**你自己机器**的 `~/.mibu-video`(Windows:`C:\Users\<你>\.mibu-video`),app 本体之外——升级 / 重装不丢数据。

下一步:[快速上手](/start/quickstart/)。
