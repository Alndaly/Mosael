---
title: 项目信息
description: 开源地址、作者、许可、下载与反馈渠道。
sidebar:
  order: 1
---

## 开源地址

源码托管在 GitHub:**[Alndaly/mibu-cut](https://github.com/Alndaly/mibu-cut)**。

- 桌面安装包:[GitHub Releases](https://github.com/Alndaly/mibu-cut/releases)(macOS arm64 `.dmg` / Windows x64 安装器,推 tag 后由 CI 自动打包上传)
- 问题反馈 / 功能建议:[GitHub Issues](https://github.com/Alndaly/mibu-cut/issues)

## 作者

**Kinda Hall**(GitHub [@Alndaly](https://github.com/Alndaly))。

## 许可

Mibu **源码开放但非开源软件**,采用专有许可(全文见仓库根目录 [LICENSE](https://github.com/Alndaly/mibu-cut/blob/main/LICENSE)):

- 允许:出于评估、学习与**个人非商业**用途查看源码、本地构建与运行。
- 禁止:任何商业用途(售卖、付费服务、SaaS 托管、集成进商业产品)与再分发。
- 商业授权:请通过 GitHub 联系版权人另行取得书面许可。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 桌面壳 | Electron(内置发布执行器,驱动内嵌浏览器登录 / 上传) |
| 前端 | Vite + React + TypeScript + Tailwind |
| 后端 | FastAPI(Python)+ SQLite,单一事实源;PyInstaller 打包进应用 |
| AI 智能体 | 托管外部 coding-agent CLI(opencode 式),经 Mibu MCP server 使用工具 |
| 文档站 | Astro Starlight(本站) |

所有用户数据落在本机 `~/.mibu-cut`,不依赖云端。
