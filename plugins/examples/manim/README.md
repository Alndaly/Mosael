# Manim Teaching Animation for Mosael

Teaching animations with [Manim Community](https://docs.manim.community/) — the community edition of the engine behind 3Blue1Brown's maths videos. Derivations, geometry, function plots, algorithm steps, code walk-throughs and physics diagrams, rendered on your computer with no video generation model and no per-video cost.

用 [Manim 社区版](https://docs.manim.community/)(3Blue1Brown 数学动画的那套引擎)做教学动画:公式推导、几何关系、函数图像、算法步骤、代码讲解、物理示意。在本机渲染,不调用视频生成模型,不按条计费。

## 什么时候用它

- **要「一步一步地变」、而且必须讲对的内容**(公式、图像、步骤、代码)→ 用它。
- **要真实画面**(人物、场景、实拍感)→ 用视频生成模型。
- **排版精致的图文卡片、数据图表** → [Remotion 插件](https://mosael.com/zh/plugins/remotion)也合适;两者都装着时,讲数学、几何、算法优先 Manim。

## 四个工具

| 工具 | 做什么 | 默认开放 |
| --- | --- | --- |
| 准备 Manim 环境 `manim_setup` | 建 Python 环境、装 Manim、查 LaTeX、试渲一帧;缺什么逐条说怎么装 | 是 |
| Manim 讲解视频 `manim_explainer` | 给结构化内容出讲解视频,不写代码 | 是 |
| Manim 自定义动画 `manim_animation` | 给一段 Manim 场景代码,画什么都行 | **否** |
| Manim 静帧 `manim_still` | 同上,只要最后一帧(PNG) | **否** |

四个工具都会边跑边报进度(工作流执行面板里看得到「第 2/5 段:勾股定理」);在工作流或任务里取消时,Manim 连同它起的 LaTeX 进程一起停下。

**第一次请在插件页先运行一次「准备 Manim 环境」。** 渲染工具不会顺手装环境:装一次要一到几分钟,而渲染工具的预算是按「智能体一次最多等 180 秒」定的。

### 讲解视频

标题页 → 一步一步讲 → 要点回顾。每一步可以有:

- **标题**、**旁白**(显示成底部字幕,也决定这一步多长 —— 按朗读速度算,中文每秒约 4.5 字)、**要点**(随旁白逐条出现);
- 再配**一样**视觉:**LaTeX 公式**(最多 3 条,逐条书写)、**函数图像**(`sin(x) + x^2/8` 这样的算式,自动定坐标范围,渐近线处断开)、或**代码**(语法高亮,按 `[2, "4-6", 9]` 依次框住讲解的行)。

画幅 16:9 / 9:16 / 1:1 / 4:3 / 3:4,画质 480p–4K,深色 / 浅色主题,自定强调色与字体。返回值里的 `steps` 是每一步**实际渲出来**的起止时间;打开 `subtitles` 还会同时交出一份按句切好的 `.srt` —— 给旁白配音、对字幕都用得上。

内容**从不拼进代码**:场景是插件自带的一份固定文件,内容经 JSON 交给它;文字进 `Text`(纯文本),公式先挡掉 `\input`、`\write18`、`\def` 这类读写文件、定义命令的写法,函数算式用语法树求值(不经 `eval`,只认数字、`x`、四则运算与白名单里的函数)。

### 自定义动画怎么写

```python
from manim import *
from mosael import DATA   # 调用时传的 data


class Sorting(Scene):
    def construct(self):
        values = DATA.get("values", [5, 2, 4, 1, 3])
        bars = VGroup(*[Rectangle(width=0.8, height=v * 0.6, fill_opacity=0.8, color=BLUE) for v in values])
        bars.arrange(RIGHT, buff=0.2, aligned_edge=DOWN)
        self.play(FadeIn(bars))
        self.play(Swap(bars[0], bars[1]))
        self.wait()
```

代码里只有一个场景类时 `scene` 可留空。格式 mp4 / webm / mov / gif,可透明背景(mp4 会改成 mov)。报错会指出**第几行哪一句**(`第 12 行 self.play(Swapp(a, b)):NameError: …`),改了再调即可;语法错误在起 Manim 之前就说。

## 安全:自定义动画会在本机执行 Python

自定义动画和静帧执行的是**任意 Python 代码**,以你的身份在这台电脑上运行。所以:

- 这两个工具**默认不开放**,要在插件页的工具列表里自己勾上;
- 开放之后,智能体每次调用它们都**先出一张确认卡**(清单里声明为 `"effects": "local-code"`),写明
  「会在你的电脑上运行代码」和代码开头,你批准了才跑;插件页里它们旁边标着「需确认」;
- 默认有一道**护栏**:只准 import 画图用得到的模块(manim、math、numpy、scipy、networkx、random …),不准用 `open`、`exec`、`__import__`,不准碰 `os.system`、`np.save` 之类。护栏挡的是随手写出、或被一段网页诱导写出的越界代码,**它不是沙箱**;
- 确实需要别的库时,在插件配置里打开「不限制自定义代码」,后果自负。

讲解视频不执行你给的任何代码,默认开放。

## 要求与安装

Manim 需要 Python 3.11+(插件用随 Mosael 发的那个 Python,不用你装),以及:

| 系统 | 装 Manim 之前要有 | LaTeX(可选,公式排版用) |
| --- | --- | --- |
| **Windows** | 什么都不用 —— 依赖都有现成的二进制包 | [MiKTeX](https://miktex.org/download),安装时允许自动安装缺的宏包 |
| **macOS** | `brew install cairo pkg-config`(pycairo 没有 macOS 的二进制包,要编译),以及 `xcode-select --install` | [MacTeX](https://www.tug.org/mactex/),或 `brew install --cask mactex-no-gui` |
| **Linux** | Debian/Ubuntu:`sudo apt install build-essential pkg-config libcairo2-dev libpango1.0-dev`;Fedora:`sudo dnf install gcc pkg-config cairo-devel pango-devel` | `sudo apt install texlive texlive-latex-extra dvisvgm` |

- **不需要 ffmpeg**:Manim 0.19 起用 PyAV 编码,PyAV 的二进制包里自带 FFmpeg 的库。
- **LaTeX 是可选的**:没有它,讲解视频把公式写成一行 Unicode(`a² + b² = c²`、`(-b ± √(b²-4ac))/(2a)`)照样出片,结果里会说明;自定义动画里的 `MathTex` / `Tex` 用不了,会得到一句「没装 LaTeX」和装法。想用精简的 TinyTeX,Manim 文档列了要装的宏包。
- 约 **350 MB** 磁盘空间,装在 Mosael 数据目录的 `plugin-data/dev.mosael.manim` 下。插件更新不会重装;卸载插件时一起删掉。Mosael 升级后自带的 Python 挪了位置,环境自动接过去;换了次版本(比如 3.13 → 3.14),渲染工具会说清楚,再运行一次「准备 Manim 环境」按新版重建。
- 「准备 Manim 环境」装之前先查系统依赖,缺什么直接说装哪几个,不让你对着一屏编译报错猜。

### 插件配置

- **PyPI 镜像**:国内网络可以填 `https://pypi.tuna.tsinghua.edu.cn/simple`。
- **已装 Manim 的 Python**:已经用 conda / uv 装好 Manim 的,填那个环境里 python 的完整路径,就不再装一份。
- **不限制自定义代码**:见上面「安全」。

## 权限

- `process:spawn`:启动 Python / Manim / LaTeX,以及执行自定义动画的代码。
- `network:pypi`:准备环境时从 PyPI 安装 Manim。渲染本身不联网(已关掉 Manim 渲完后查新版本的那次请求)。
- `filesystem:write`:写插件自己的数据目录。

## 版本与许可

Manim 0.21.0(锁定精确版本;插件升级换了版本时,渲染工具会提醒再运行一次「准备 Manim 环境」,它按新版本重装)。Manim 社区版是 [MIT 许可](https://github.com/ManimCommunity/manim/blob/main/LICENSE.md);插件不分发 Manim 的代码,而是在你的电脑上从 PyPI 安装。
