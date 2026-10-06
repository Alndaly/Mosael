# ADR 0041:本机服务 —— 插件声明一个常驻进程,宿主替它起停、看健康、收日志;ComfyUI 能选目录启动,也能让 Mosael 装

## Status

Accepted — 2026-10-06。下面「已拍板」的七条由维护者于 2026-10-06 批准(全部按推荐);其余是照这七条定下的实现细节。

## Context

ComfyUI 插件现在只会**连一台已经在跑的服务器**:填 `server_url`,别的都不管。两种人用不上:

- **本机装过 ComfyUI 的**:每次要先自己开终端、激活环境、`python main.py`,关了 Mosael 还得记得去关它(显存一直占着);
- **本机没装的**:要自己搞定 Python、torch 选哪个版本、CUDA 和驱动对不对得上、ComfyUI-Manager 怎么装 —— 这一步劝退大多数人。

### 现在有什么

- **随包的 Python 和每个引擎一个 venv**:`core/interpreter.py` 的 `base_python()`(打包版由 Electron 设
  `MOSAEL_TTS_BASE_PYTHON` 指向随包的 CPython 3.13;开发时是 `build/python/bin/python3`);转写、配音、人声分离各自
  `venv-<engine>`。`drop_venvs_built_on_another_python` 会删掉建在别的 Python 小版本上的 `venv-*`。
- **装依赖**:`core/pip_install.py` 的 `install()` —— 用设置里的 pip 源(`pip_index_url`,预设 pypi / 清华 / 阿里 / 腾讯),
  完整输出落盘(`logs/pip-*.log`),失败翻成人话(`explain`)。安装进度是内存里的 `InstallStore`,前端按 1200 ms 轮询
  (`pollWhileUnsettled`)。**装之前不查剩余空间**,磁盘满了只能事后从 pip 的输出里认出来。
- **常驻进程**:`ai/runtime/worker_pool.py` 的 `ResidentWorker` 走 stdin/stdout 管道,没有端口、没有 HTTP 健康检查、崩了不退避;
  `core/child_process.py` 有 `own_group` / `kill_tree` / `popen_text`;后端退出时 `lifespan` 关掉各个池子,
  `core/lifeline.py` 盯着 Electron 的 pid,壳没了就退。Electron 管后端那一套(`backend-lifecycle.cjs`):`/api/health`
  轮询、5 分钟内最多重启 3 次、1 秒起翻倍退避、退出时先 SIGTERM 再 SIGKILL。
- **插件工具一次调用一个子进程**(`domain/plugins/runtime.py` 的 `execute_tool`,默认 60 秒,可流式、可取消),跑完就退 ——
  扛不住一个要一直开着的服务。宿主调插件的操作走 `tools.invoke_host`(按能力找工具,比如模型库的 `{"op":"library"}`)。
  插件的持久目录 `plugin-data/<id>` **卸载插件时一起删**。
- **ComfyUI 插件**:每个连接是一行 `PluginInstance`,插件从环境变量读 `SERVER_URL`;每台服务器的本地数据按
  `sha1(server_url)` 分文件;工作台的内嵌视图、编辑器地址、pysssss 的预览图链接都从这个地址来。pysssss 从 `/extensions` 认,
  Manager 从 `/v2/manager/version`(V4)认,装节点后的重启走 `/v2/manager/reboot`。
- **谁能在这台机器上跑代码**:桌面版由 `MOSAEL_LOCAL_DESKTOP=1` 认出(`settings.local_desktop`);引擎安装、插件安装、
  安装源设置都要部署管理员(`ensure_deployment_admin`)。插件工具的 `effects` 有 `local-code` 一档(ADR 0023)。

### 外部事实(2026-10-06 查证)

- **ComfyUI 0.39.0** 的 README:Python 3.13「支持得很好」(3.14 能跑,个别自定义节点有问题);NVIDIA 装 torch 用
  `--extra-index-url https://download.pytorch.org/whl/cu130`;**Manager 已经并进 ComfyUI**:
  `pip install -r manager_requirements.txt`(装的是 pip 包 `comfyui_manager`,当前 4.2.2),启动加 `--enable-manager`。
  老办法(git clone 进 `custom_nodes/comfyui-manager`)还能用。
- **Manager 的安全档**(`user/__manager/config.ini`):不只听本机(`--listen` 不是回环地址)时,从未登记来源装节点、
  `pip install` 这类高风险操作默认被拦。
- **在测试场实测**(Apple 芯片、随包 CPython 3.13.15、经代理;脚本和日志在会话的 scratchpad,不进仓库):
  - 下 0.39.0 源码包 49 MB;PyPI 上的 torch 2.14.1 直接带 MPS(`torch.backends.mps.is_available()` 为真),装 torch 53 秒、
    venv 769 MB;`requirements.txt` 164 秒,venv 1.8 GB;`manager_requirements.txt` 13 秒;pysssss 544 KB。
    **装完一共 2.0 GB,pip 缓存另占 788 MB。**
  - 启动命令 `python main.py --listen 127.0.0.1 --port 18188 --enable-manager`;前端 1.53.10。
  - **pysssss(ComfyUI-Custom-Scripts)在 0.39.0 上照常能用**:模型库的 Range 读、算哈希、存预览图这几天一直靠它测。
    它的 README 写着作者很忙、维护跟不上 —— 记作风险,见 Consequences。
  - Manager 的「重启」在非 Desktop 版里是重新执行同一条命令(日志:`Restarting... [Legacy Mode]`)。
- **官方 ComfyUI Desktop** 自己管进程和自己的 Python 环境,默认端口 8000。

## Decision

### 已拍板(维护者,2026-10-06)

| # | 问题 | 定了 |
| --- | --- | --- |
| 1 | 架构 | **通用的「插件声明本机服务」**,应用里不出现 ComfyUI 的特例 |
| 2 | Mosael 装哪种 | **自己建 Python 环境 + 固定版本的 ComfyUI 源码**,不是引导去装 Desktop,也不用 comfy-cli |
| 3 | 首期平台 | **Apple 芯片 Mac、Windows + NVIDIA**;别的平台先给明确的说明 |
| 4 | 什么时候起 | **用到时自动起,退出 Mosael 时停**;另给一个「保持运行」开关 |
| 5 | 模型放哪 | **默认在安装目录里,也能指向已有的模型文件夹共用** |
| 6 | 局域网 | **默认只听本机**,要别的机器连得手动打开 |
| 7 | 装完下不下模型 | **不下**,引导去模型库 |

### 1. 一个连接,三种「在哪跑」

ComfyUI 连接多一项**在哪跑**:

| 方式 | 地址从哪来 | Mosael 管什么 |
| --- | --- | --- |
| 连一台服务器(现在就有) | 用户填 | 只连,不管进程 |
| 用我自己装的(选目录) | `http://127.0.0.1:<端口>`,宿主填 | 起、停、重启、看日志、看健康;**不改用户的安装**(补装 pysssss 要先问) |
| 让 Mosael 装一个 | 同上 | 下载、装、起停、更新、卸载 |

后两种把算出来的地址**写进连接的 `server_url`**:插件、工作台、模型库、工作流库读的还是那一个地址,一行都不用改。
端口在建连接时选定、记下(从 8189 往上找第一个空的;8188 留给用户自己开的那一台),以后一直用它 —— 每台服务器的本地数据
按地址分文件,端口一变就对不上。端口能在「高级」里改,改的时候插件把按旧地址存的那几份文件搬到新地址名下。

### 2. 分两层:宿主管进程,插件管 ComfyUI 的细节

**插件清单**(版本 8)多一个字段 `services`,声明「我有一种本机服务」:

```jsonc
"services": [
  { "key": "comfyui", "title": "ComfyUI", "tool": "comfyui_generation" }
]
```

`tool` 是认领这件事的那个工具(和能力一样,一种服务只归一个工具,ADR 0033)。老清单经 `upgrade()` 迁移:没有这个字段就是
没有服务。社区收稿、装包时同一个 `parse()` 校验。

**插件那个工具多几个操作**(宿主经 `invoke_host` 调,只描述、不起进程):

| 操作 | 输入 | 回什么 |
| --- | --- | --- |
| `service_detect` | 目录;可选:用户指定的 Python | 认没认出来;ComfyUI 版本、用哪个 Python、torch 版本、显卡(mps / cuda / 只有 CPU)、显存;有没有 Manager(pip 包 / 老式节点 / 没有)、pysssss;能读懂的问题列表 |
| `service_launch` | 目录、Python、端口、听不听局域网、附加参数 | `argv`、`env`、`cwd`、健康检查的路径(`/system_stats`)、首次就绪最多等多久 |
| `service_plan` | 目标目录 | 这台机器能不能装、装哪种 torch、要多少空间、分几步 —— 给确认页 |
| `service_install` | 目标目录、`service_plan` 的结果 | 流式进度(第几步、多少字节),可取消、可接着装 |
| `service_add_nodes` | 目录 | 补装 pysssss(用户点头之后) |

**宿主的「本机服务」**(后端新加的领域模块 `local_services`)不认识 ComfyUI,只认上面那张表:

- **状态**:已停止 / 启动中 / 运行中 / 崩溃了在重启 / 起不来。界面按 1200 ms 轮询,和引擎安装一样。
- **起**:`own_group` 起子进程;环境里带上 HuggingFace 镜像(`HF_ENDPOINT`,沿用现有设置)和这个连接的出站代理设置。
  stdout / stderr 进一份环形缓冲(最近 2000 行,界面能看),同时落盘 `logs/service-<连接>.log`(滚动)。
- **就绪**:每 500 ms 请求一次健康检查路径,直到插件给的上限(第一次启动要解包前端、加载自定义节点,默认 180 秒)。
- **崩溃**:运行中意外退出 → 自动重启,1 秒起翻倍,5 分钟内最多 3 次(和 Electron 管后端是同一条规矩);超过就停在
  「起不来」,把最后 40 行日志摆出来。
- **重启**:宿主自己做(停了再起)。插件装完节点要重启时,本机服务的连接走宿主的重启,不调 Manager 的 `/v2/manager/reboot`
  —— Manager 在 Windows 上重启是另起一个进程、旧的退出,宿主会以为它崩了,也就再也停不掉它。
- **停**:SIGTERM 整组,10 秒后 `kill_tree`。后端正常退出时 `lifespan` 停掉全部。
- **没来得及停**(后端被强杀、断电):起进程时记一份 pid 文件(pid、启动时间、命令行);下次后端启动时,那个进程还在、
  命令行对得上、健康检查通过,就**接回来**当作运行中;对不上就不碰它。
- **同一个目录只起一份**:按目录的真实路径加锁;两个连接指同一个目录,第二个直接说「这个目录已经由某某连接在跑」。
- **用到时起**(拍板 4):`invoke_host` / `execute_tool` 要对一个本机服务的连接干活,先 `ensure_running` —— 停着就起,
  等它就绪再跑;任务里显示「正在启动本机 ComfyUI」。工作台打开前先请宿主起好。
- **保持运行**:Mosael 一启动就起,不等用到;退出 Mosael 时照样停 —— Mosael 起的进程不留在后台。
- 连接、目录、端口、局域网开关、保持运行、附加参数存在宿主的新表 `local_services`(一行对一个插件实例),带迁移。

这样以后别的插件(比如一个要常驻的本机解析服务)用同一套,应用里不会有 ComfyUI 的特例。

### 3. 选目录启动

- **认出 ComfyUI**:目录里有 `main.py` 和 `comfy/`。Windows 便携版用户常选外层那个目录(`ComfyUI_windows_portable`),
  里面是 `ComfyUI/` 和 `python_embeded/`,两种都认。
- **认出 Python**,按顺序:便携版的 `python_embeded`;目录里或上一层的 `venv` / `.venv`;都没有就请用户自己指一个
  (conda、系统 Python)。认出来先**试跑一次**(`import torch`,看 MPS / CUDA 能不能用,30 秒上限),结果直接摆出来;
  torch 都导入不了就不让起,说清楚是哪一步不行。
- **起的参数**:`--listen 127.0.0.1 --port <端口>`;装了 Manager 的 pip 包就加 `--enable-manager`(老式节点不用加);
  「高级」里能加 `--lowvram` 这类参数。不改它的任何文件。
- **pysssss**:模型库的哈希、预览图要靠它。没装就在连接页上说明少了什么,点「补装」并确认后,把**插件里钉死版本**的压缩包
  解到它的 `custom_nodes/ComfyUI-Custom-Scripts`,写明装到了哪儿,下次起生效。
- **发现已经在跑的**:插件页上探一下本机 8188、8000(Desktop 的默认端口)的 `/system_stats`,有 ComfyUI 就提示「本机发现一个,
  要连上吗」—— 建的是「连一台服务器」那一种。Desktop 自己管自己的进程,Mosael 不去起它、也不去停它。

### 4. 让 Mosael 装

- **装在哪**:宿主分配的 `<数据目录>/local-services/<连接>/`,里面是 `ComfyUI/`(源码)和 `.venv/`。**不放插件的持久目录**:
  那个目录卸载插件时一起删,模型也会跟着没。卸载插件时如果还有 Mosael 装的 ComfyUI,先问要不要一起删。
- **用哪个 Python**:随包的 CPython(`base_python()`)。装好时把 Python 小版本记进安装记录;以后 Mosael 升级换了小版本,
  连接页说「运行环境要重建」,一键重装依赖,源码和模型不动。这个 venv 不叫 `venv-*`,不归
  `drop_venvs_built_on_another_python` 管。
- **步骤**(每一步做完记一笔,断了再点「接着装」从没做完的那一步开始):
  1. 查剩余空间:Mac 至少 5 GB,Windows + CUDA 至少 8 GB(CUDA 版 torch 大得多),不够就不开始;
  2. 下固定版本的 ComfyUI 源码包(GitHub),按插件里钉死的 sha256 校验,解开;
  3. 建 venv,升级 pip;
  4. **装 torch**(见下);
  5. `requirements.txt`、`manager_requirements.txt`(用设置里的 pip 源);
  6. 下 pysssss(钉死版本 + sha256);
  7. 试起一次,健康检查通过才算装好。
- **torch 装哪种**(最容易出错的一步,全在插件里):
  - **Apple 芯片 Mac**:PyPI 上的就带 MPS(实测)。
  - **Windows + NVIDIA**:PyPI 上的 torch 只有 CPU 版,必须走 PyTorch 自己的 CUDA 源。用 `nvidia-smi` 读驱动版本、显卡、
    显存,按插件里的对照表挑这块驱动撑得住的最高 CUDA 版本(对照表随固定版本一起更新)。**新增设置「PyTorch 源」**
    (官方 / 国内镜像几个预设),现有的「pip 源」管不到这一块。
  - **Intel Mac、AMD、只有 CPU、Linux**:这一版不装,说清楚原因,建议「用我自己装的」或者连一台服务器。
- **下载**:GitHub 的压缩包走现有的代理设置;另可配一个 GitHub 镜像地址前缀 —— 压缩包按 sha256 校验,镜像换不了内容。
  HuggingFace 沿用现有的镜像设置。
- **装完不下模型**(拍板 7):装好之后的那一页直接链到模型库;已经有模型文件夹的,引导到「共用模型文件夹」。
- **共用模型文件夹**(拍板 5):用 ComfyUI 自己的 `extra_model_paths.yaml` 指过去(以前 A1111 / Forge / 另一份 ComfyUI 的
  `models`),不拷第二份;模型库下载的新文件仍落在安装目录自己的 `models`。
- **更新、回滚、卸载**:「更新 ComfyUI」= 换到新的固定版本 —— 新源码解到旁边,装依赖前先 `pip freeze` 存一份,失败就换回
  旧源码、按那份装回去;卸载删安装目录,模型文件夹可以选保留(移到 `<数据目录>/local-services/kept-models/`)。

### 5. 安全

- **起一个目录里的代码 = 在这台机器上运行它**。选目录、补装 pysssss、开始安装,各确认一次,卡上写明会在哪台机器上运行。
- **只有部署管理员能建、改、起本机服务**(`ensure_deployment_admin`):桌面版就是你自己;多人部署时进程跑在服务器上,
  普通成员只能用管理员建好的连接(和现在用别人建的连接一样)。
- **默认只听 127.0.0.1**(拍板 6)。打开局域网(`--listen 0.0.0.0`)时明说:ComfyUI 自己没有登录,同一网络里的人都能用它
  提交任务、看到所有出图;Manager 也会因此拦下一部分安装。

### 6. 分三步

1. **本机服务框架 + 选目录启动 + 发现已经在跑的**:清单版本 8 的 `services`、`local_services` 表和迁移、宿主的进程管理
   (起停、健康、崩溃退避、日志、pid 接回、目录锁、用到时起、保持运行)、管理接口和连接页上的「本机服务」卡片;
   插件的 `service_detect` / `service_launch` / `service_add_nodes`;重启走宿主。
2. **让 Mosael 装**:Apple 芯片 Mac、Windows + NVIDIA;`service_plan` / `service_install`、空间检查、接着装、torch 选择、
   「PyTorch 源」和 GitHub 镜像前缀两项设置、Python 小版本变了重建环境。
3. **补充**:共用模型文件夹、更新与回滚、卸载保留模型、闲置一段时间自动停(释放显存)、Linux 服务器。

**测试**:
- 宿主:拿一个假服务(几行 Python 的 HTTP 服务,能按指令慢启动、崩、不响应)测起停、就绪超时、崩溃退避和上限、
  停掉整个进程组、pid 接回与不接、目录锁、端口被占、用到时起。
- 插件:用夹具目录测 `service_detect`(便携版两种选法、venv、`.venv`、缺 torch、Manager 两种装法);`service_install`
  对着本地起的假下载源跑一遍步骤、断点、sha256 不对、空间不够。
- 真机:Mac 上用测试场那份 ComfyUI 走「选目录启动」和「让 Mosael 装」全程;**Windows + NVIDIA 要一台真机**,
  第二步交付前请维护者配合跑一遍。

### 第一步做成了什么(2026-10-06,实现记录)

照上面做的,另有几处 ADR 没说、实现时定下的:

- **子进程的 stdout / stderr 直接写日志文件,不写管道**:后端被强杀之后管道没了,ComfyUI 下一次写日志(tqdm 进度条)就是 EPIPE,
  正在跑的生成会失败;写文件不受影响,接回来以后宿主接着读同一个文件。环形缓冲是从文件拉的(看日志、看状态、看护线程每秒一次),
  回车刷新的进度条只留最后一下;「滚动」= 每次从头起之前挪成 `.1` `.2` `.3`,一直开着超过 10 MB 时抄一份再截断。
- **第一次就没起来的不重试**(参数不对、缺依赖、端口被占几乎总是每次都一样),直接「起不来」;运行中崩了才退避重启。重启的那一次
  还没就绪就退出,照样算一次崩溃。
- **后台刷新目录不替它起进程**:就绪之后那次、启动时那次、每分钟问指纹、改配置之后对齐,都包在 `service_gate.no_autostart`
  里;停着的连接干脆跳过,它就绪时自己通知刷新一次。真机上撞到过:一个刚就绪就崩的服务,就绪后那次刷新正好撞上它崩了、替它又起了
  一次,「5 分钟内 3 次」就此失效。
- **等就绪不攥数据库连接、不占插件名额**:插件调用之前那道门(`service_gate.prepare`)只「停着就替它起进程」,交回「等它就绪」;
  等的那一段在 `plugins/tools._plugin_slot` 交还连接之后、占插件名额之前 —— 第一次起要几十秒到一两分钟,别的调用不该陪它等。
  本机服务的领域函数自己不提交(领域层不提交的棘轮),建、改、删的提交在路由的 `Tx` 上。
- **插件怎么知道「这台归宿主管」**:宿主给本机服务的连接在插件进程里放 `MOSAEL_LOCAL_SERVICE=<key>`;ComfyUI 的 `reboot` 看到它就
  交回 `host_restart`,工作流库的重启由宿主停了再起。宿主这一侧只认 `host_restart`,不认识 Manager。
- **宿主写哪一格地址**:清单格式定死 `server_url`(`SERVICE_ADDRESS_FIELD`),声明了 `services` 却没有这一格文本配置的清单装不上。
- **端口被占的判断**带 SO_REUSEADDR 试绑(POSIX):刚停掉的服务端口上挂着健康检查留下的 TIME_WAIT,不带它「重启」会被当成端口被占。
- **用户指定的解释器优先于自动找到的**(他可能有理由不用那个 venv);**便携版加 `-s`**,和它自己的启动脚本一样。
- **改端口**多了一个插件操作 `service_readdress`(按旧地址存的模型库缓存、工具对照搬到新地址名下),只能停着改。
- **认目录也查 requirements.txt 里必需的包**(「non essential」那句注释以下的不算,只认装没装):在维护者自己那份 ComfyUI 0.38 上
  实测撞到 —— conda base 里 torch 2.8、MPS 都好,起起来却因为缺 alembic、comfy-aimdo 直接退出;只查 torch 会把它放过去。
- **检查结果不落库**:存下来的目录是确认过的,打开连接卡时不自动试跑,要看点「重新检查」。
- **认目录、补装、建改起停都要部署管理员**;`ensure`(工作台打开前请宿主起好)只要是连接的主人。本机发现也只给部署管理员。
- **ComfyUI 插件的权限清单没加 GitHub**:补装 pysssss 要从 codeload.github.com 下载。加一项会让每个已有连接升级后都先停用、等重新
  授权 —— 留给维护者定。

**Windows 上没验过**:`CREATE_NEW_PROCESS_GROUP` 加 CTRL_BREAK 的「请它自己退」、`taskkill /T` 停整组、PowerShell 读进程命令行
(接回时核对)、便携版 / `Scripts\python.exe` 的真机路径、端口探测在 Windows 上的语义,都只有单测(夹具目录)或照文档写的。

## 这一版不做

- 管官方 ComfyUI Desktop 的进程(只发现、只连)。
- Intel Mac、AMD(ROCm / DirectML)、只有 CPU 的安装;Linux 放到第三步。
- 一个目录起多份、同一份 ComfyUI 给几个连接各起一个;ComfyUI 的 `--multi-user` 模式(和 ADR 0038 一样)。
- 装完自动下模型。
- 关掉 Mosael 后进程留在后台。

## Consequences

- 装过 ComfyUI 的人选一次目录就能用,不用再开终端;没装过的点一下就有一台,Mac 上约 2 GB、几分钟(看网速)。
- 宿主多了一个通用的进程管理器和一张表,插件清单升到 8;以后别的插件要常驻进程不用再在应用里加特例。
- 工作台、模型库、工作流库、生成都不知道 ComfyUI 是怎么来的 —— 它们只看 `server_url`。
- 本机服务的连接,装节点后的重启改走宿主;Manager 页面里用户自己点「重启」的那一下在 Windows 上会让宿主失去这个进程 ——
  宿主发现它退出后端口又活了,就提示「它被别处重启了,点这里接回来」,第一步在 Windows 上验证。
- pysssss 维护跟不上是风险:它要是和某个新版 ComfyUI 不兼容,固定版本先不升,同时考虑把模型库要的那几个路由
  (Range 读、元数据、存预览图)做成 Mosael 自己的小节点。
- PyTorch 和 CUDA 的对照表、固定的 ComfyUI 版本、两个压缩包的 sha256 都在插件里,要跟着上游定期更新。
