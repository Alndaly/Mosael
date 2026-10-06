# 本机服务(ADR 0041)真机验证 —— Windows + NVIDIA、Linux 服务器

状态:**待跑**。Mac(Apple 芯片)三步都在隔离环境里实测过(见 ADR 0041 的实现记录);下面两台这边没有,要维护者找机器跑。
跑完一项勾一项,出问题的把现象和日志(连接页「本机服务」卡片里的「看日志」)记在那一项下面。

## Windows + NVIDIA

**准备**:一台 Windows 10 / 11 + NVIDIA 显卡的机器,装 Mosael(带这一版)。

1. [ ] 从 ComfyUI 插件 1.14 升上来:连接先停用,插件页出「授予这 3 项」(GitHub、PyPI、PyTorch),授予后恢复。
2. [ ] 「让 Mosael 装」的计划页:
   - 认出 `nvidia-smi`,显示驱动版本、显卡名、显存;
   - RTX 20 系及更新 + 驱动 ≥ 580 → 选 cu130;GTX 10 系及更老(驱动 ≥ 560.76)→ 选 cu126;
   - 驱动太老、没有 NVIDIA 显卡:各有一句说清楚的话,不让装;
   - 空间写「至少 8 GB」;系统没开长路径(LongPathsEnabled = 0)时有提醒;
   - 「会从这几处下载」那里写明经哪个代理、哪几处直连。
3. [ ] 完整装一遍:
   - 带和不带 GitHub 镜像前缀各一次,PyTorch 源官方和南京大学各一次;
   - 建出 `.venv\Scripts\python.exe`,装上的 torch 带 `+cu130` / `+cu126`;
   - 显卡自检通过、试起通过,日志里有 `--enable-manager` 和 cuda;
   - 模型库能打开。
4. [ ] 下载中、装依赖中各取消一次:没有残留的 `python.exe` / pip 进程,半截文件清掉了,「接着装」能接上。
5. [ ] 同一个目录同时装两份:第二份说「另一个安装在用这个目录」。
6. [ ] Mosael 换了自带 Python 版本后「运行环境要重建」能一键重建;经 Mosael 自己的代理设置下载正常。
7. [ ] 「选择…」:选文件夹的对话框有「新建文件夹」;选文件能选到 `python_embeded\python.exe`;连远程服务器时没有这个按钮。
8. [ ] 便携版、只有老式 `custom_nodes\comfyui-manager`(没有 pip 版):
   - 检测给出提醒,附上 `python_embeded\python.exe -m pip install -r …\manager_requirements.txt`;
   - 照样能起,不加 `--enable-manager`。
9. [ ] 「用我自己装的」「让 Mosael 装」两种方式下不显示「服务器地址」那一行;切回「连一台服务器」又出来。
10. [ ] 更新和回到上一版(真的改名、搬目录):
    - 0.38.0 → 0.39.0 更新成功,models、custom_nodes、user、input、output 都在;
    - 回到上一版成功;
    - `models` 里有个文件被别的程序占着时更新:失败并说「已经换回」,文件都在。
11. [ ] 共用模型文件夹:Windows 路径、放在另一块盘上的文件夹都能被认出、列进模型库,那个文件夹里什么都没被改。
12. [ ] 删连接时删掉 Mosael 装的那一份:很大的 `.venv`(只读文件、超长路径)删得掉;「保留模型」的模型挪到了 kept-models。
13. [ ] 闲置自动停:设成 1 分钟,闲着会停;有任务在跑时不停;下次用到时自动起来。

## Linux 服务器(x86_64 + NVIDIA)

**准备**:一台较新的发行版(glibc ≥ 2.28)+ NVIDIA 显卡的服务器,Mosael 以服务器方式部署,用部署管理员账号操作。

1. [ ] 计划页:RTX 显卡 + 驱动 ≥ 580.65.06 → cu130;Pascal(GTX 10 系)+ 560.x 驱动 → cu126。
2. [ ] RTX + 575 驱动:说驱动太老,点名要 580.65.06。
3. [ ] 完整装一遍(同 Windows 第 3 项),`.venv/bin/python`,试起通过,模型库能打开。
4. [ ] Docker 里:不带 `--gpus all` 时说没有 NVIDIA 显卡并提示 `docker run --gpus all`;带上之后能装。
5. [ ] CentOS 7(glibc 太老)、Alpine(musl)、ARM 服务器:计划页拒绝,说清楚原因。
6. [ ] Mosael 在 Linux 上自带的 Python 能建 venv。
7. [ ] 「用我自己装的」:指向一份已经装好、带 venv 的 ComfyUI,检测、启动正常。
8. [ ] 更新、回到上一版、删除(同 Windows 第 10、12 项)。
9. [ ] PyTorch 源选南京大学时,`nvidia-*`、`triton` 这些依赖也能从它下到(这一项这边没验证过)。

## 结果

(跑完填:日期、机器、勾了几项、问题和对应的修复提交。)
