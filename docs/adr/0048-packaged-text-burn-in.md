# ADR 0048:打包版也烧得了字幕和花字

## Status

Accepted — 2026-10-09。草稿 2026-10-08(全项目体检 MED-4);四个待拍板点由**维护者 2026-10-09 按推荐拍板**(体检编号 D12–D15),
落成下面「拍板」一节。第一步(D14:ffmpeg 路径存进设置、改文案、启动探测上界面)与本篇同一次提交,见文末「实现记录」;
D12(随包带 chromium-headless-shell)、D13(前端 dist 用 asarUnpack 外置)**发版时和桌面壳那一路一起做**,这次不动打包;
D15(libass 字号对齐)不在本篇处理。

## Context

### 现象:发布版的 Mac 用户,时间线上有字幕 / 花字 / AI 标识就导不出,而且自己修不了

烧字有两条路(ADR 0004「预览即导出」要的是文字一致):

1. **浏览器渲 PNG**(首选,和预览逐像素对齐):无头 Chromium 按前端那套 CSS 把每条字幕 / 花字渲成透明 PNG,再由 ffmpeg 叠上去。
   不需要 ffmpeg 带 libass。
2. **libass 烧 ASS**(回落):ffmpeg 的 `subtitles` / `ass` 滤镜。预览和导出的字号历史上对不齐(`_ASS_FONTSIZE_SCALE`),
   和 ADR 0004 想要的一致性有差距。

两条在打包版上都走不通:

- **第一条走不到。** 渲 PNG 要两样东西:前端构建产物(`frontend/dist`,里面的 `index-*.css` 带 `@font-face`),和一个能起的 Chromium。
  - `find_frontend_dist()` 在没有 `MOSAEL_FRONTEND_DIST` 时按 `backend/app/media/text_render.py` 相对仓库结构找
    `parents[3]/frontend/dist`。打包后后端是 PyInstaller 的 onedir,那个相对路径不存在;前端 dist 被打进了 `app.asar`
    (`package.json` 的 `files` 列了 `frontend/dist/**`,没有 asarUnpack),Python 读不到 asar 里的文件;`MOSAEL_FRONTEND_DIST`
    全仓只有后端在读,`electron/main.cjs` 起后端时没有注入它(只经 `loginShellPath()` 合并了 PATH)。所以 `_text_rasterizer_available()`
    在打包版上**恒为 False**。
  - 渲 PNG 用 Playwright 的 Chromium(`text_render.py` 里 `sync_playwright().chromium.launch(...)`),而打包版不带 Playwright 的浏览器
    二进制(ms-playwright 缓存不在包里)。
- **第二条看运气。** 只剩 libass 这条路,而很多 Mac 用户的 ffmpeg 来自 Homebrew 的 core 版,没有 libass(本机实测:
  `/opt/homebrew/bin/ffmpeg` 没有 `subtitles` / `ass` / `drawtext`)。这时 `ensure_text_can_burn` 在建任务之前就抛 `renderErr_noLibass`。
- **给的修法对发布版没用。** `renderErr_noLibass` 让用户「设 `MOSAEL_FFMPEG` 指向带 libass 的 ffmpeg」。可 Electron 只从登录 shell 取
  PATH,shell rc 里设的环境变量传不到后端;从 Finder 启动的应用根本不读 shell rc。于是这句修法在发布版上做不到。
- **启动时其实探过,但用户看不见。** 后端启动时探一次 libass,结论只写一行 `logger.warning`;要等带字幕的导出被拒才知道。

### 为什么开发和 CI 发现不了

开发态后端相对路径能找到 `frontend/dist`、本机装了 Playwright 的 Chromium,第一条路通;CI 用的也是完整环境。这个缺口只在**打包产物 + 用户机器上那把 ffmpeg** 的组合里出现。

### 数字

- 本机实测:Homebrew `ffmpeg 9.0.2`(core 版)`-filters` 里没有 `subtitles` / `ass` / `drawtext`;也没有 webp 编码器(同一批精简)。
- 现在导不出的触发面:时间线上任何字幕轨、花字、AI 标识(发布合规要的水印)。

## Decision

目标:**打包版默认走第一条路(浏览器渲 PNG),而且这件事不依赖用户机器上的 ffmpeg 有没有 libass。** 下面三条一起,缺一条第一条路仍走不通。

### 1. 前端 dist 要能被后端读到

前端构建产物放到 asar 外、给后端一个真实文件路径:在 `package.json` 里用 `asarUnpack`(`frontend/dist/**`)把已经在 `files` 里的那份
标记成不打进 asar;`electron/main.cjs` 起后端时注入 `MOSAEL_FRONTEND_DIST` 指向那个路径。`find_frontend_dist()` 已经优先读这个环境变量,
后端侧不用改。

### 2. 随包带一个能起的 Chromium

随包带 `chromium-headless-shell`(Playwright 的无头壳,比完整 Chromium 小很多),设 `PLAYWRIGHT_BROWSERS_PATH` 指向它。渲 PNG 只用无头壳就够。

### 3. ffmpeg 路径存进设置,不靠环境变量

- 「管理 → 引擎 → FFmpeg」一节里加一格「ffmpeg 路径」,存库。填的是这台机器上要执行的程序,所以只有部署管理员能看、能改,
  和装本机引擎同一条权限。保存时先确认它是一个能跑的 ffmpeg(绝对路径、文件在、能执行、`-version` 认得出),不是就不存,说清是哪儿不对。
- 生效:起 ffmpeg 的地方一律读 `settings.ffmpeg` / `settings.ffprobe`,所以填的那份在启动时、保存之后写回这两项。
  填的 ffmpeg 旁边有 `ffprobe` 就一起用;没有就还用 PATH 上的。
- `MOSAEL_FFMPEG` 仍可覆盖:环境变量给了就以它为准,这一格整个不生效(开发、测试、容器部署靠它钉死 ffmpeg),界面和报错都照实说。
- `renderErr_noLibass` 改成说原因和怎么办:这个 ffmpeg 没有 libass(Homebrew 默认装的就是这种精简版),装完整版
  (`brew install ffmpeg-full`),再到这一格填它的路径。环境变量钉住时换一句:改环境变量、重启。
- 启动时探一次 ffmpeg(找不找得到、版本、有没有 libass、带字的导出走哪条路),结论**显示在这一节里**,不只写日志;
  保存之后、点「重新检测」时再探。

这三条到位后,打包版默认用浏览器渲 PNG(和预览一致,不依赖 libass);libass 只作为「用户显式配了一把带 libass 的 ffmpeg」时的回落。

## 拍板(维护者 2026-10-09 按推荐拍板)

1. **D12 第一条路的浏览器用什么**:随包带 `chromium-headless-shell` + `PLAYWRIGHT_BROWSERS_PATH`(可控、比完整 Chromium 小、不依赖用户装没装
   Chrome)。不用系统 Chrome(`channel="chrome"`):用户没装 / 版本太旧时又回落 libass,等于没解决。**发版时和桌面壳那一路一起做。**
2. **D13 dist 外置用什么**:`asarUnpack`(把 `files` 里已有的那份标成不打进 asar,不多拷一份);不用 `extraResources`。
   **发版时和桌面壳那一路一起做。**
3. **D14 打包工作量没排期时的过渡**:先落决定 3(ffmpeg 路径存库 + 文案 + 启动探测上界面,纯后端 / 管理页,无打包改动),
   让配了带 libass ffmpeg 的用户至少走得通 libass;浏览器那条路随打包一起上。**本次实现。**
4. **D15 字号对齐**:libass 回落仍有 `_ASS_FONTSIZE_SCALE` 的历史差。不在本篇处理 —— 浏览器路是主路,libass 只作兜底;真要让 libass
   也对齐另开一项。

## 否掉的备选

- **随包带一个带 libass 的完整 ffmpeg。** 解得了「导不出」,但只走 libass 这条路 —— 预览和导出的字号对不齐,和 ADR 0004 的一致性目标不符;
  而且完整 ffmpeg 体积不小。可作为**退路**(若决定 1/2 的打包工作量太大,先带完整 ffmpeg 保证「导得出」,文字一致性另算)。
- **把 `frontend/dist` 留在 asar 里,让后端经 Electron 代理读。** 多一条跨进程取文件的路,PyInstaller 的后端读 asar 本来就别扭;不如直接放 asar 外。
- **只靠 `MOSAEL_FFMPEG` + 改文案教用户装 ffmpeg-full。** 现状,已证明在发布版上做不到(环境变量传不到从 Finder 启动的后端)。
- **ffmpeg 路径存库后不再读环境变量。** `DeploymentConfig` 那几项就是这么做的(库是唯一真相,环境变量只播种一次)。这里不照搬:
  测试套和 CI 靠 `MOSAEL_FFMPEG` 指到完整版来跑 libass 那条真路,容器部署也习惯用环境变量钉死二进制;而两边谁赢写成一条明确的规则
  (环境变量给了就以它为准),并在界面和报错里说出来,不会出现「改了设置却不生效、也没人说」。

## Consequences

- 第一步之后:用 Homebrew ffmpeg 的 Mac 用户,带字的导出被拒时知道是 libass 的事、知道装什么、知道去哪填;填好不用重启。
  管理页一打开就看得见这台机器上的 ffmpeg 烧不烧得了字,不用等导出失败。
- 决定 1/2 落地之后:发布版的 Mac 用户,时间线上有字幕 / 花字 / AI 标识也导得出,而且走的是和预览一致的那条路,不取决于他机器上的 ffmpeg。
- 安装包变大(多一个 chromium-headless-shell,约几十 MB;asar 外的前端 dist 和原来打进 asar 的是同一份,不额外增量)。
- 渲 PNG 要起一个无头浏览器进程:导出首次用到时起、用完回收(和现在开发态一致);Chromium 起不来时回落 libass(用户配了的话),
  都不行再在建任务前报 `renderErr_noLibass`。
- Windows / Linux 打包同理:三条都要做(dist 外置 + 注入路径、带无头壳、ffmpeg 路径存库)。

## 分步

1. 设置:「管理 → 引擎 → FFmpeg」加「ffmpeg 路径」一格(存库),改 `renderErr_noLibass` 文案,启动探测结果上界面。(D14,已做)
2. 打包:`frontend/dist` 用 asarUnpack 外置,`main.cjs` 注入 `MOSAEL_FRONTEND_DIST`。(D13,发版时和桌面壳那一路一起做)
3. 打包:带 `chromium-headless-shell`,设 `PLAYWRIGHT_BROWSERS_PATH`。(D12,同上)
4. 真机验证:发布版 Mac(Homebrew core ffmpeg)上导一条带字幕 + 花字 + AI 标识的时间线,逐像素对一次预览;Windows 同样跑一遍。

## 实现记录(2026-10-09,第一步)

- 存:单例表 `media_tools_config`(`MediaToolsConfig.ffmpeg_path`,空 = PATH 上的 `ffmpeg`)。新表由 `create_all` 建出来,不需要一次性迁移,
  库版本号不动。
- 推与探:`app/domain/media_tools.py` —— `save_path`(校验,`ffmpegPath_*`;提交之后写回 `settings` 并重探)、`apply_to_process`
  (启动装配,`app.main._prepare_network` 里和重试次数、内网名单一起)、`status` / `recheck`(启动时由 `_warm_engine_probes` 在后台探一次)。
  环境变量给了哪几项在进程起来那一刻记下(`core/config.FFMPEG_FIELDS_FROM_ENVIRONMENT`),之后 `settings.ffmpeg` 会被这一格改写。
- 带字的导出走哪条路只在一处算:`render_executor.text_burn_path()`,建任务前那一道(`ensure_text_can_burn`)和管理页的探测结果都问它。
  缺 libass 时的那句话:`renderErr_noLibass`,环境变量钉住时 `renderErr_noLibassPinnedByEnvironment`。
- 接口:`GET / PUT /api/settings/ffmpeg`、`POST /api/settings/ffmpeg/recheck`,都只给部署管理员。界面:`frontend/src/features/admin/FfmpegSection.tsx`,
  「引擎」tab 的第一节。
- 进程内状态:`settings` 的 ffmpeg / ffprobe 两项和探测结果都登记在 `docs/PROCESS_STATE.md`,测试之间由 `tests/conftest.py` 还原。
- 测试:`backend/tests/test_ffmpeg_path_is_a_setting.py`;前端 `FfmpegSection.dom.test.tsx`。
