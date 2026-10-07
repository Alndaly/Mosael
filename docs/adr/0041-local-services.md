# ADR 0041:本机服务 —— 插件声明一个常驻进程,宿主替它起停、看健康、收日志;ComfyUI 能选目录启动,也能让 Mosael 装

## Status

Accepted — 2026-10-06。下面「已拍板」的七条由维护者于 2026-10-06 批准(全部按推荐);其余是照这七条定下的实现细节。

**已交付**(2026-10-06):§6 的三步都做完了 —— 本机服务框架与选目录启动(第一步)、让 Mosael 装(第二步)、共用模型文件夹 / 更新与回滚 /
卸载保留模型 / 闲置自动停 / Linux 服务器(第三步),各步的实现记录在 §6 后面。Windows、Linux 的真机验收还欠着(清单在交付说明里)。

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
  老办法(git clone 进 `custom_nodes/comfyui-manager`,3.x)ComfyUI 那边还认,但 **Mosael 不支持它**(维护者 2026-10-06 定,
  见「第二步做成了什么」)。
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
| `service_detect` | 目录;可选:用户指定的 Python | 认没认出来;ComfyUI 版本、用哪个 Python、torch 版本、显卡(mps / cuda / 只有 CPU)、显存;有没有 Manager(pip 包 / 没有;只有 custom_nodes 里的老 Manager 时提醒不支持、给出换成 pip 版的命令)、pysssss;能读懂的问题列表 |
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
- **起的参数**:`--listen 127.0.0.1 --port <端口>`;装了 Manager 的 pip 包就加 `--enable-manager`,没装不加(custom_nodes 里的老
  Manager 不支持,起的时候不看它);
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
  - **Intel Mac、AMD、只有 CPU、Linux**:这一版不装,说清楚原因,建议「用我自己装的」或者连一台服务器。(Linux 在第三步补上了:x86_64 + NVIDIA,见第三步的实现记录。)
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

### 第二步做成了什么(2026-10-06,实现记录)

照 §4 做的;ADR 没说、实现时定下的:

- **谁做哪几步**:插件的 `service_install` 在自己的进程里做前七步(查空间、下源码、解开、建 venv 并升级 pip、装 PyTorch、装依赖、装
  pysssss),流式报进度、看取消文件,每一步做完在安装目录的 `mosael-install.json` 记一笔;**「试起一次」是宿主的**:走的就是以后真起它的
  那条路(supervisor:同一条命令、同一份环境、同一个健康检查),通过了才把这一行记成装好。起来之后让它开着(装完下一步多半就是去模型库)。
- **两份记录,说的是两件事**:插件的安装记录是续装用的流水账(做完了哪几步、venv 建在哪个 Python 小版本上、哪种 PyTorch、源码是哪个
  版本);宿主新加的 `local_services.python_minor`(带迁移)是「装好了、试起过,用的是哪个小版本」—— 连接页的「已装好 / 要重建」、
  起之前那道拦都只看它,不读插件的文件。
- **目录就是安装目录**:让 Mosael 装的那一行 `directory` 记宿主分的 `<数据目录>/local-services/<连接>/`,解释器留空;插件原来那套认目录
  (`main.py` 在 `ComfyUI/` 里、上一层有 `.venv`)正好认得出,认目录、怎么起、补装和「用我自己装的」走同一段代码。
- **pip 缓存由宿主给**:`<数据目录>/local-services/pip-cache`,几份安装共用 —— 接着装、重建运行环境不重下,也不把几个 GB 塞进这个人自己
  的 pip 缓存;第三步卸载时一起清。源码包不做字节级续传:codeload 现打包、不给长度也不认 Range,12.6 MB,断了整个重下。
- **PyTorch 钉版本,CUDA 的带后缀**:`torch==2.14.1`、`torchvision==0.29.1`、`torchaudio==2.11.0`(torchaudio 从 2.11 起不跟着 torch
  发版);CUDA 版写成 `torch==2.14.1+cu130`,换了 CUDA 源 pip 才认得「不是装着的那个」,PyPI 上同版本号的 CPU 版也混不进来。CUDA 版只用
  PyTorch 源(`--index-url <根>/cu130`,依赖也在那个索引里),Mac 的走 pip 源。**装依赖不加 `--upgrade`**:requirements.txt 里没写版本的
  `torch` 会被升级成 pip 源上的那个 —— Windows 上就是 CPU 版(ComfyUI README 里「Torch not compiled with CUDA enabled」的来历);装完依赖
  再核对一次 torch 的版本没变。装完 PyTorch 在显卡上真算一次 1 + 1:CUDA 版在算力不对的卡上能导入、`is_available()` 也是真,第一次算才报错。
- **对照表**(2026-10-06 查 download.pytorch.org 和 NVIDIA 的 CUDA 13.4 Update 1 发行说明):torch 2.14.1 + cp313 + Windows 只有 cu126 /
  cu130 / cu132 三个源有包,cu128 停在 2.11.0,cu132 没有 torchaudio;ComfyUI 0.39.0 自己的 Windows 便携版用 cu130,README 说 20 系及以上
  必须 cu130、cu126 那一版「DO NOT USE … ON NEWER 20 SERIES AND ABOVE」。所以表里两行:cu130 要 R580 以上、算力 ≥ 7.5;cu126 要 560.76
  以上、算力 5.0–7.0。算力另问一次 `nvidia-smi --query-gpu=compute_cap`(老驱动不认这一项,问不到就按 20 系及以上挑,装完试显卡会兜住)。
  20 系的卡配 570 系的驱动不降级到 cu126,直说升级驱动。
- **空间**按十进制 GB(和界面、系统一个数):要「至少 5 / 8 GB」减去安装目录已经占的。Windows 没开长路径支持、安装目录又长到放不下 torch
  最深的那个文件(wheel 中央目录实测 127 个字符)时,计划里就报错、不开始。
- **同一个目录两次一起装**:插件装的时候攥着 `install.lock`(fcntl / msvcrt,进程没了锁自己松开)—— 后端被强杀时上一次的插件进程可能还在跑。
- **pip 失败说人话在插件里**:插件进程只有标准库、碰不到宿主的 `core/pip_install`,所以那套规矩(`--prefer-binary`、`--timeout 60`、
  `--retries 10`、挑 `ERROR:` 结论行不取尾巴、常见病因)照抄了一份,双语,并按这一步说下一步换哪个源(CUDA 版 PyTorch → 「PyTorch 源」,
  别的 → pip 源);完整输出写进宿主给的 `logs/service-install-<连接>.log`(raw 进度行不进日志),界面上「安装日志」看它。
- **进度**:流式协议多一种 `{"event": "step", …}`(`StreamHooks.on_step`,可选):开头一行列出有哪几步,之后每一步开始、字节、正在下哪个
  文件(pip 用 `--progress-bar raw`)、做完;速度由宿主按同一个文件的字节和时间算(`core/rate` 的 `DownloadRate`,换文件重新量)。安装不占插件名额(和流式生成一样)。进度在宿主内存里,
  界面 1200 ms 轮询;后端重启就没了,磁盘上的流水账还在 —— 安装计划据此打勾,「接着装」从没做完的那一步开始。后端退出、删连接、卸插件时
  正在装的先取消。
- **没装好、正在装、要重建都不让起**,用到时起也报这一句;正在装时不能换目录、不能改回「连一台服务器」、不能再装一次。
- **换成「用我自己装的」时安装目录留着**(再选「让 Mosael 装」接着用它);删连接也留着 —— 删它、保留模型是第三步的卸载。
- **本机的两种「在哪跑」不摆「服务器地址」那一格**(维护者看了真机截图后提):第一步只在存好之后才把它变成只读,选上、还没「检查并使用」
  时它还能填,写着「本机默认是 http://127.0.0.1:8188」。现在一选上就换成本机服务卡片里只读的「地址」—— 还没建这一行时说端口确认后由
  Mosael 分(从 8189 往上找空的),建好了是写进连接的那个(两种本机方式之间换,端口不变),改端口在「高级」里;换回「连一台服务器」
  那一格回来,还是连接现在的值。连接页按清单的 `services` 和 `SERVICE_ADDRESS_FIELD` 认这一格,不认是哪个插件;模型库读不出来时
  「去检查连接设置」定位到卡片里的那一行。
- **路径格旁边的「选择…」**(系统的选文件夹 / 选文件对话框,主进程 `dialog:pickPath`):只在桌面版、连着本机后端时有 —— 选出来的是这台
  电脑上的路径,网页版或者经服务器切换连着别处时在那边没有意义。选好的和敲进去的一样,确认之后才拿去检查(检查会运行那个目录里的代码)。
  选解释器不解析链接:`.venv/bin/python` 是指向基础解释器的链接,解析掉就丢了那个环境。
- **「PyTorch 源」只收实测能当 simple 索引用的**:官方、南京大学(download.pytorch.org/whl 的镜像,带 sha256,cu126 / cu130 对着
  Windows cp313 用 pip dry-run 解析通;教育网 mirrors.cernet.edu.cn 也跳到它)。阿里云的 pytorch-wheels 是 find-links 那种平铺目录、而且
  没同步到 2.14.1;上海交大是 simple 索引,但从这台机器连它每次都要 30 秒;清华、中科大、腾讯、华为、北外、浙大、南科大、北大没有这个镜像。
  自定义的填 simple 索引的根。「GitHub 镜像前缀」存成以 `/` 结尾,只接在 GitHub 的地址前面;选目录那一种的「补装 pysssss」也走它。
- **确认之后机器变了就不装**:安装带着确认页上的 `flavour`,插件装之前再看一次,对不上(换了驱动)请人重新看计划。
- **安装计划分 `supported` 和 `ok`**:前者是这台机器本身能不能装,后者还看空间、路径 —— 「这块盘只剩 2 GB」不该说成「这台机器装不了」。
- **权限一次补齐**:清单加 `network:github`、`network:pypi`、`network:pytorch`(插件 1.15.0)—— 第一步的补装 pysssss 本来就要连 codeload,
  当时没申报。升上来的连接照规矩先停用、等授予。
- **不再支持老的 ComfyUI-Manager**(维护者 2026-10-06 定,取代第一步的「老式节点」一档):Manager 要么是 pip 包(V4,ComfyUI 0.4.0 起
  自带 —— 核对过 v0.3.78 没有 `manager_requirements.txt`、v0.4.0 起有),要么当作没有。`/v2/manager/version` 只认 V4 起,回 V3 也当
  没有;不再探老的 `/manager/version`。下模型、装节点包、重启碰上没有能用的 Manager 时说同一句:要 V4,`pip install -r
  manager_requirements.txt`、启动加 `--enable-manager`。「用我自己装的」:装了 pip 包就加 `--enable-manager`;只有
  `custom_nodes/comfyui-manager` 时认目录报一条 warning(不支持、装缺的节点包和经它下模型要 pip 版,给出那两条命令;ComfyUI 老到还没有
  `manager_requirements.txt` 就先升级),照样能起、不加参数、不碰那个目录。「让 Mosael 装」的那一份装的就是 pip 包,总是加。

实测(Apple 芯片 M 系列、经代理、官方 PyPI,隔离数据目录,经界面):pip 缓存是热的(测试场那份)从确认到试起通过 85 秒(源码 5 秒、
torch 21 秒、依赖 24 秒、试起 23 秒);全新的缓存 280 秒(torch 68 秒、依赖 181 秒、试起 23 秒);装完 1.9 GB,pip 缓存另 0.8 GB。
重建运行环境(Python 小版本改成 3.12 造出来)61 秒,源码和 models 里的文件不动。下载中取消、pip 下 torch 下到一半取消再「接着装」,
半截的都不留下,从那一步接着来;镜像给了别的内容时 sha256 拦下、什么都不解;放在 2 GB 的盘上,计划里就说空间不够、按钮是灰的,硬调接口
也停在查空间那一步。

**Windows 上没验过**:nvidia-smi 的解析、对照表、Windows 路径、计划的判定只有夹具单测;CUDA 版 PyTorch 真装、真跑、长路径、`msvcrt`
锁都要一台 Windows + NVIDIA 的真机(验收清单在交付说明里)。

### 第三步做成了什么(2026-10-06,实现记录)

照 §4 末尾和 §6 第 3 条做的;ADR 没说、实现时定下的:

- **共用模型文件夹**(拍板 5)走 ComfyUI 自己的 `--extra-model-paths-config`:配置**写在 Mosael 的数据目录里**
  (`<数据目录>/local-services/<连接>/extra_model_paths.yaml`,两种「在哪跑」都写这一处,起的时候宿主把这一格作为 `config_dir`
  交给插件),不写进用户的 ComfyUI 目录。内容写成 JSON(也是合法的 YAML),路径一律绝对、不用 `base_path`(ComfyUI 会对它
  expandvars)。认两种样子:ComfyUI 的 `models`(选 ComfyUI 目录也认;子目录同名对上,`clip` → `text_encoders`、`unet` →
  `diffusion_models`、`t2i_adapter` → `controlnet` 照 ComfyUI 自己的老名字并过去)、A1111 / Forge(照 ComfyUI 自带的
  `extra_model_paths.yaml.example`,Forge 的 `text_encoder` 也算)。**认得出才存**,最多 20 处。**只读**:模型库下载的新文件落在
  它自己的 `models`(哪怕共用的那一处排在前面),共用那几处的模型不往旁边存预览图、不按哈希找(pysssss 会写一份 `.sha256`),
  改按文件名和大小找;插件调用的环境里多 `MOSAEL_LOCAL_SERVICE_SHARED` 说是哪几处。连接页上每一处写明认成什么、在跑的话它加载了
  没有、看到几个模型(按 `/experiment/models` 报的路径数)。卸载时保留下来的那几份出现在「一键加回来」里。
- **闲置自动停**:`local_services.idle_stop_minutes`(缺省 30,0 = 不停,最多一天;「保持运行」的不停)。「用它」= 插件调用开始和
  **用完**时(一次生成跑二十分钟,从跑完算)、请它起好、工作台 / 内嵌编辑器亮着(前端每两分钟 `POST …/touch`,只记一笔、不替它起)、
  就绪的那一刻;后台刷新目录不算。看护线程每分钟看一遍,闲置够久的**先问插件 `service_busy`**(ComfyUI:`/queue` 里有在跑、在排的
  就是有活)—— 有活钟重新算,问不到不停,问的那一会儿又有人用上了也不停。停了记下是闲置停的,卡片和用不了的那一句都这么说。
- **更新与回滚**(插件 `versions`):钉死的版本是一张表(0.38.0、0.39.0,sha256 都下过两次一致),新装装最新的。「更新」= 查空间、
  下新源码、解到旁边(`ComfyUI.next`)、**装依赖之前 `pip freeze` 存一份**(`pip-freeze-<旧版本>.txt`)、换上新源码(旧的改名
  `ComfyUI.previous`;`models`、`custom_nodes`、`user`、`input`、`output` 五样**搬过去**,新包自带的占位目录、示例节点里旧的没有的
  补进去)、装新依赖(不加 `--upgrade`,装完核对 torch 没变)、确认 pysssss 在,宿主再试起一次。**venv 不重建**。换上之前出错:删掉
  旁边的新源码,原来的没动;换上之后出错或取消:插件自己换回去(不看取消);试起没通过(或这时取消):宿主让插件换回去,说「新版本 x
  试起没通过:…。已经换回 y」,换回也出错就两件都说。换回去 = 五样搬回、换回旧源码、按 freeze **只把版本变了的包**装回(`--no-deps`;
  PyTorch 三件、`-e`、`@ 地址` 的不进对比)、删掉换下来的那份。**上一版留一步**:更新成了以后 `ComfyUI.previous` 和那份 freeze 留着,
  「回到上一版」不重下;下一次更新开始换源码时才删(先从记录里去掉再删,删到一半断了也不会被当成能回去的那一版)。每一步做完记一笔:
  被强行打断(后端被杀、断电)记录里留着 `updating` / `restoring`,`service_launch` 不起它、安装不在它上面接着装,连接页上「换回 y」
  从停下的地方收拾干净;换回时目的地已经有的那一样不动(说明它还没搬过来,另一边那个是新包的占位),免得把真数据当占位删掉。
  宿主这边一次安装多了 `kind`(install / update / rollback)和 `target`,进度、取消、日志和装是同一套,试起那一步共用。
- **卸载**:删连接、卸载插件时问要不要一起删 `<数据目录>/local-services/<连接>/`,可以「保留模型」—— 插件的 `service_uninstall` 说
  这里是不是一份让 Mosael 装的、模型文件夹在哪、多大(换版本被打断在搬五样的中途时,模型还在上一版那里);**挪走、删目录都是宿主做**:
  插件说的模型文件夹必须在安装目录里面,挪到 `kept-models/<连接的名字>`(同名的加「 (2)」);删的只是宿主分的那个目录 —— 它本身是链接
  只删链接,里面的链接也只删链接,选目录那一种指向的用户目录从来不碰(那里只有宿主写的共用模型配置,跟着连接删)。删之前先停掉它、
  取消正在装的。只有部署管理员删得了;缺省留着(接口不说就不删)。卸载插件时它的连接还留着这样的目录,**不说怎么处置就 409**,界面上
  一起问一次。最后一份让 Mosael 装的没了,共用的 pip 缓存一起清。
- **Linux 服务器**(x86_64 + NVIDIA):和 Windows 同一张对照表,驱动下限每个 CUDA 源记两列 —— CUDA 13.0 Linux 580.65.06(CUDA 13.0 的
  发行说明里那一行;Windows 照 13.x 的「R580 及以上」)、CUDA 12.6 Linux 560.28.03。核对过 download.pytorch.org:三件都有 cp313 的
  `manylinux_2_28_x86_64` 包;Linux 上的 CUDA 版另要 nvidia-cudnn / cusparselt / nccl / nvshmem(cu126 还有 nvjitlink)和 triton,
  同一个 PyTorch 源里都有对应版本,只用 `--index-url` 那一个源装得全(cu130 约 1.75 GB,cu126 约 2.5 GB)。随包的 Python 多报一项系统的
  glibc(`platform.libc_ver`,运行时的那个),**低于 2.28 不装**(CentOS 7 的 2.17 装上去 pip 只会说「找不到这个版本」),认不出是 glibc
  (Alpine 的 musl)也不装;ARM 的 Linux 不装;没有 NVIDIA 显卡时多一句容器里要把显卡带进来(`docker run --gpus all`)。nvidia-smi 在
  PATH 上找不到时再看 `/usr/bin` 和容器里 NVIDIA 运行时放的 `/usr/local/nvidia/bin`。「用我自己装的」本来就不分系统。
- **安装计划写明下载怎么走**(维护者看计划页时问「这里的下载是不能走代理的吗」):就是插件进程拿到的那一份(`egress.resolve`,和
  child_env 同一个决定)—— 跟随全局并且全局设了代理 / 这个连接自己的代理 / 直连 / 跟随全局而全局没设(照系统的走),代理里的账号密码
  换成 `***`;每个地址标出是否在绕过列表里直连、被「下载源」里的哪一项改写、那一项此刻是什么。
- **用不了的时候按本机服务的状态说**(维护者在真机上看到本机连接也写着「确认它在运行、地址填对」):`issue_of` → 正在装 / 正在换版本
  / 还没装好 / 要重建 / 停着(含闲置停的)/ 正在起 / 起不来(带原因)/ 进程在却不应答;插件调用失败时经 `service_gate.explain` 换成这一句,
  连接卡片、生成模型那一行、模型库、工作流库、打开工作台都照它说。「连一台服务器」照旧。

实测(Apple 芯片 Mac,隔离数据目录,经界面):

- 共用模型文件夹:用户自己那份 ComfyUI 的 `models`(115 GB、25 个模型文件)给「用我自己装的」和「让 Mosael 装」两个连接共用,重启后
  各自加载、数出 25 个,模型库列全;经模型库下一个小文件落在自己的 `models/vae`;`find -newer` 标记文件:那个文件夹里一个文件都没变。
- 闲置自动停:分钟数设成 1,21:35:16 起、21:37:02 自动停下(看护线程每分钟一次),卡片上写「闲置了 1 分钟,自动停了」。
- 更新与回滚:先让插件装钉死的 0.38.0(界面上总装最新的,这一份是直接调插件装、再在界面上「接着装」试起;339 秒,pip 缓存半热);
  更新到 0.39.0 用了 13 秒(pip 缓存热,含试起 5.6 秒),`comfyui_version` 变成 0.39.0,三个包升级(frontend 1.53.6 → 1.53.10、
  workflow-templates 0.11.70 → 0.11.76、comfy-kitchen 0.2.36 → 0.2.37),五样里放的标记文件都在;回到 0.38.0 用了 8 秒,三个包原样装回,
  `ComfyUI.previous` 和 freeze 都清掉;把 pip 源指向一个空的索引再更新,装依赖那一步失败,5 秒后已经换回 0.38.0、照常能起(指向一个
  拒绝连接的地址时 pip 重试了 4 分钟,结果一样)。
- 卸载:删那个 0.38 / 0.39 来回换过的连接,确认框写明 1.9 GB、模型 23 KB 和挪到哪;确认后 2 秒删完,模型连同标记文件挪到
  `kept-models/<连接的名字>`,另一个让 Mosael 装的连接的「共用的模型文件夹」里多了它这一条建议;还有一份让 Mosael 装的在用,pip 缓存留着。

**Windows、Linux 上没验过**:Linux 的判定、nvidia-smi、对照表的 Linux 列、glibc 只有夹具单测;CUDA 版 PyTorch 真装、真跑要一台
Linux + NVIDIA 的服务器(验收清单在交付说明里,和第二步的 Windows 清单合在一起)。

### 新建连接时就选在哪跑(2026-10-07,实现记录)

维护者:「ComfyUI 插件的新建连接这里表单就有问题了 —— 因为支持多种方式,但这个新建连接的表单仅支持服务器地址。」三种「在哪跑」原来
只在建好之后的连接卡片上,本机的两种得先建一个「连一台服务器」再改。现在:

- **弹窗一开头就是「在哪跑」**(清单声明了 `services` 才有;和卡片同一个组件)。用我自己装的:目录、可选的解释器,点「新建」确认一次
  会运行这个目录里的代码,建好马上认一遍,结果放进卡片「重新检查」那一份缓存 —— 新连接展开就是认目录的结果,不再问第二次;认不出照样建好,
  卡片上标红、「换一个」重选(卡片上换成这一种时仍是「能起才存」)。让 Mosael 装:只建那一行,展开就是安装计划,不替人开始装。
  本机的两种不摆服务器地址;别的配置项三种都有,凭据照旧在建好的连接上。
- **一个事务建好**:新建连接的接口多一个可选的 `local_service`(`mode`、`directory`、`python`、`confirm_run_code`)。宿主
  `inst.add`(只 flush)→ 原来那套 `configure` / `records.make_managed`(选端口、写地址)→ `inst.commit_created`(提交之后才通知
  替宿主做事的那一侧:它对齐失败会回滚会话)。哪一步不成,连接一行都不留下 —— 分两步建会剩一个地址是缺省 8188 的「连一台服务器」。
  `set_config` 拆出不提交的 `write_config`,`records.create` / `make_managed` 用它;领域层的 commit 数不变。
- **地址归宿主**:清单里 `server_url`(SERVICE_ADDRESS_FIELD)是必填的,本机的两种填的就是宿主选的那个端口;客户端给了也不用,
  不让客户端先编一个地址。只认这一格的名字,不认是哪个插件。
- **权限一起授予**:宿主不替还没授予权限的连接问插件(第一步定的),而建好马上要认目录、看安装计划 —— 所以弹窗把插件声明的权限列出来,
  接口多一个 `grant_permissions`,建好时一起授予(清单没声明的授予不了,连接不留下)。「连一台服务器」照旧建好之后在卡片上授予。
- **要部署管理员**(和卡片同一条):别人那两颗是灰的、说为什么;不带 `local_service` 的新建照旧谁都能做。
- 建好之后页面滚到新连接(几个连接时它排在最下面);本机发现的「连上」也滚过去,建的照旧是「连一台服务器」。

实测(Apple 芯片 Mac,隔离数据目录,经界面):自己解开的一份 ComfyUI 0.39.0(phase 1 的源码包和 pip 缓存)用「用我自己装的」新建,
8189 正被别的进程占着,分到 8190;建好卡片上就是认目录的结果(0.39.0、PyTorch 2.14.1、MPS、pip 版 Manager,提醒少了 pysssss),
点「启动」十几秒后运行中。「让 Mosael 装」新建后展开就是安装计划(装在数据目录的 `local-services/<连接>`),没有开始装。
把那份 ComfyUI 临时开在 8188,本机发现的「连上」建出的是「连一台服务器」(权限照旧等授予)。

## 这一版不做

- 管官方 ComfyUI Desktop 的进程(只发现、只连)。
- Intel Mac、AMD(ROCm / DirectML)、只有 CPU、ARM 的 Windows / Linux 的安装。
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
