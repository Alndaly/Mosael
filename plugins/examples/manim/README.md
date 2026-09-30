# Manim Teaching Animation

Teaching animations with [Manim Community](https://docs.manim.community/) — the community edition of the engine behind 3Blue1Brown's maths videos: derivations, geometry, function plots, algorithm steps, code walk-throughs and physics diagrams. Rendered on your computer, with no video generation model and no per-video cost.

## When to use it

- **Content that has to "change step by step" and must be correct** (formulas, plots, steps, code) → use this.
- **Realistic footage** (people, places, a live-action feel) → use a video generation model.
- **Polished text-and-image cards, data charts** → the [Remotion plugin](https://mosael.com/en/plugins/remotion) also fits; when both are installed, prefer Manim for maths, geometry and algorithms.

## Four tools

| Tool | What it does | Enabled by default |
| --- | --- | --- |
| Prepare Manim `manim_setup` | Creates the Python environment, installs Manim, checks for LaTeX, test-renders a frame; tells you item by item how to install anything missing | Yes |
| Manim explainer `manim_explainer` | Makes an explainer video from structured content, no code needed | Yes |
| Manim custom animation `manim_animation` | Takes a piece of Manim scene code; draw anything | **No** |
| Manim still `manim_still` | Same as above, but only the last frame (PNG) | **No** |

All four tools report progress as they run (the workflow run panel shows something like "Part 2/5: Pythagorean theorem"); when you cancel from a workflow or task, Manim stops together with the LaTeX processes it started.

**The first time, run "Prepare Manim" once from the plugin page.** The rendering tools do not install the environment on the side: an install takes one to several minutes, while the rendering tools are budgeted around "an agent waits at most 180 seconds per call".

### Explainer videos

Title page → step-by-step explanation → key takeaways. Each step can have:

- a **title**, **narration** (shown as subtitles at the bottom; it also sets how long the step lasts — based on reading speed, about 150 words per minute in English or about 4.5 characters per second in Chinese) and **key points** (appearing one by one along with the narration);
- plus **one** visual: **LaTeX formulas** (up to 3, written out one after another), a **function plot** (an expression like `sin(x) + x^2/8`, with the axis ranges chosen automatically and breaks at asymptotes), or **code** (syntax highlighted, boxing the lines being explained in order, e.g. `[2, "4-6", 9]`).

Aspect ratios 16:9 / 9:16 / 1:1 / 4:3 / 3:4, quality 480p–4K, dark / light theme, custom accent color and font. The `steps` in the result are the start and end times each step **actually rendered** at; turning on `subtitles` also returns an `.srt` split by sentence — handy for voicing the narration or syncing subtitles.

Content is **never spliced into code**: the scene is a fixed file shipped with the plugin, and the content is handed to it as JSON. Text goes into `Text` (plain text); formulas first have constructs that read or write files or define commands, such as `\input`, `\write18` and `\def`, blocked; function expressions are evaluated from a syntax tree (not via `eval`; only numbers, `x`, arithmetic and whitelisted functions are accepted).

### Writing a custom animation

```python
from manim import *
from mosael import DATA   # the data passed with the call


class Sorting(Scene):
    def construct(self):
        values = DATA.get("values", [5, 2, 4, 1, 3])
        bars = VGroup(*[Rectangle(width=0.8, height=v * 0.6, fill_opacity=0.8, color=BLUE) for v in values])
        bars.arrange(RIGHT, buff=0.2, aligned_edge=DOWN)
        self.play(FadeIn(bars))
        self.play(Swap(bars[0], bars[1]))
        self.wait()
```

When the code contains only one scene class, `scene` can be left empty. Formats are mp4 / webm / mov / gif, with optional transparent background (mp4 is switched to mov). Errors point to **which statement on which line** (`Line 12 self.play(Swapp(a, b)): NameError: …`), so fix it and call again; syntax errors are reported before Manim is even started.

## Security: custom animations run Python on your computer

Custom animations and stills execute **arbitrary Python code**, running on this computer as you. So:

- these two tools are **not enabled by default**; you have to tick them yourself in the tool list on the plugin page;
- once enabled, every time the agent calls them it **shows an approval card first** (declared as `"effects": "local-code"` in the manifest), stating
  "This runs code on your computer" along with the start of the code, and it only runs once you approve; on the plugin page they are marked "Asks first";
- by default there is a **guardrail**: only modules useful for drawing may be imported (manim, math, numpy, scipy, networkx, random …); `open`, `exec` and `__import__` are not allowed, nor are things like `os.system` or `np.save`, nor reading local files into the picture without `open` (`SVGMobject` / `ImageMobject` reading by path, `Code(code_file=…)`, `\input` in formulas). The guardrail stops out-of-bounds code written carelessly or induced by a web page; **it is not a sandbox**;
- if you really need other libraries, turn on "Unrestricted custom code" in the plugin configuration, at your own risk.

Explainer videos do not execute any code you give them, and are enabled by default.

## Requirements and installation

Manim needs Python 3.11+ (the plugin uses the Python that ships with Mosael, so you don't install it), plus:

| System | Needed before installing Manim | LaTeX (optional, for typesetting formulas) |
| --- | --- | --- |
| **Windows** | Nothing — all dependencies have prebuilt binary packages | [MiKTeX](https://miktex.org/download); allow it to install missing packages automatically during setup |
| **macOS** | `brew install cairo pkg-config` (pycairo has no macOS binary package and must be compiled), plus `xcode-select --install` | [MacTeX](https://www.tug.org/mactex/), or `brew install --cask mactex-no-gui` |
| **Linux** | Debian/Ubuntu: `sudo apt install build-essential pkg-config libcairo2-dev libpango1.0-dev`; Fedora: `sudo dnf install gcc pkg-config cairo-devel pango-devel` | `sudo apt install texlive texlive-latex-extra dvisvgm` |

- **No ffmpeg needed**: since Manim 0.19, encoding uses PyAV, whose binary packages bundle the FFmpeg libraries.
- **LaTeX is optional**: without it, explainer videos write formulas as a single line of Unicode (`a² + b² = c²`, `(-b ± √(b²-4ac))/(2a)`) and still produce the video, noting this in the result; `MathTex` / `Tex` in custom animations will not work, and you get a "LaTeX is not installed" message with install instructions. If you want the slimmed-down TinyTeX, the Manim docs list the packages to install.
- About **350 MB** of disk space, installed under `plugin-data/dev.mosael.manim` in the Mosael data directory. Plugin updates do not reinstall it; uninstalling the plugin deletes it too. When a Mosael upgrade moves its bundled Python, the environment is taken over automatically; if the minor version changes (e.g. 3.13 → 3.14), the rendering tools say so clearly — run "Prepare Manim" again to rebuild for the new version.
- "Prepare Manim" checks system dependencies before installing and tells you exactly which ones are missing, instead of leaving you to guess from a screen of compiler errors.

### Plugin configuration

- **PyPI mirror**: choose it in this connection's settings (Tsinghua / Alibaba / Tencent / custom); by default it follows Admin → Download sources.
- **Python with Manim**: if you already installed Manim with conda / uv, enter the full path of that environment's python, and no second copy is installed.
- **Unrestricted custom code**: see "Security" above.

## Permissions

- `process:spawn`: starts Python / Manim / LaTeX, and executes custom animation code.
- `network:pypi`: installs Manim from PyPI when preparing the environment. Rendering itself does not go online (the request Manim makes after rendering to check for new versions is turned off).
- `filesystem:write`: writes to the plugin's own data directory.

## Version and license

Manim 0.21.0 (pinned to the exact version; when a plugin upgrade changes the version, the rendering tools remind you to run "Prepare Manim" again, which reinstalls the new version). Manim Community is [MIT licensed](https://github.com/ManimCommunity/manim/blob/main/LICENSE.md); the plugin does not distribute Manim's code but installs it from PyPI on your computer.
