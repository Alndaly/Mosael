# Remotion Animation for Mosael

Make animated videos with code: lesson explainers, formula walk-throughs, code demos and data charts. Rendering happens on your computer with [Remotion](https://www.remotion.dev) — no video generation model and no per-video cost.

用代码做动画视频:知识点讲解、公式推导、代码演示、数据图表。在本机用 [Remotion](https://www.remotion.dev) 渲染,不调用视频生成模型,不按条计费。

## 什么时候用它

- **要讲准确的东西**(文字、公式、步骤、数字)→ 用它。字就是字,公式由 KaTeX 排版,代码逐行出现。
- **要真实画面**(人物、场景、实拍感)→ 用视频生成模型(如 Seedance)。

## 许可(请先读)

Remotion 不是 MIT 许可。按 [Remotion License](https://www.remotion.dev/license):

- **免费**:个人;员工不超过 3 人的营利组织;非营利组织;评估阶段。商用也可以。
- **需要购买公司许可**:员工 4 人及以上的营利组织。购买见 [remotion.pro](https://www.remotion.pro/license),拿到的密钥填在插件凭据「Remotion 许可证密钥」里。

这个插件不分发 Remotion 的代码:它在你的电脑上用 npm 从官方源安装 Remotion。**被许可的一方是你**。

## 要求

- **Node.js 18 或更新版本**(带 npm)。从 [nodejs.org](https://nodejs.org) 安装;装好后重启 Mosael。
- 约 **250 MB** 磁盘空间:Remotion 与渲染用的浏览器,装在 Mosael 数据目录的 `plugin-data/dev.mosael.remotion` 下。插件更新不会重装;卸载插件时一起删掉。

## 三个工具

| 工具 | 做什么 | 耗时 |
| --- | --- | --- |
| 准备渲染环境 `remotion_setup` | 装 Remotion、备好渲染用的浏览器 | 第一次几十秒到几分钟;之后几乎瞬间 |
| 讲解视频 `remotion_explainer` | 给标题和每一节的要点 / 公式 / 代码 / 提示,套模板出片 | 30 秒的视频约 20–40 秒 |
| 自定义动画 `remotion_animation` | 给一段 Remotion 组件代码,画什么都行 | 取决于内容 |

产出的 mp4 直接进素材库。讲解视频支持横屏 16:9、竖屏 9:16、方形 1:1,深色 / 浅色,自定强调色;每段多长按内容自动算。

**第一次请在插件页先运行一次「准备渲染环境」。** 渲染工具在环境缺失时也会自动补,但智能体单次调用最多等 180 秒,首次安装可能超过。

## 国内网络

- **npm 装不动**:在插件配置「npm 镜像」填 `https://registry.npmmirror.com`,再运行一次「准备渲染环境」。
- **浏览器下不下来**:Remotion 自带的浏览器从 Google 的服务器下载。下载失败时插件会自动改用本机的 Chrome / Edge;也可以在「浏览器路径」里直接填它们的可执行文件路径。

## 自定义动画怎么写

代码是一个 TSX 模块,`export default` 一个组件,组件收到 `{ data }`(调用时传的 `data`):

```tsx
import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";

export default function Scene({ data }: { data: { word: string } }) {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{ background: "#111", color: "white", justifyContent: "center", alignItems: "center", fontSize: 120 }}>
      <span style={{ opacity: interpolate(frame, [0, 20], [0, 1]) }}>{data.word}</span>
    </AbsoluteFill>
  );
}
```

只能 import `react`、`remotion`、`katex`。打包或渲染出错时,报错(文件、行、列)原样返回,改了再调即可。

## 权限

- `process:spawn`:启动 node / npm。
- `network:npm`:第一次准备环境时从 npm 源安装依赖、下载渲染用的浏览器。渲染本身不联网。
- `filesystem:write`:写插件自己的数据目录。

## 版本

Remotion 4.0.526、React 19.3.0、KaTeX 0.18.7,均锁定精确版本(`tools/project/package.json`)。插件升级换了版本时会自动重装。
