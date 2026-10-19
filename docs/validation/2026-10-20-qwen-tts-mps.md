# Qwen3-TTS 在 Apple MPS 上的真机验证(2026-10-20)

**结论:A —— 能在 MPS 上跑,且结果一致;不需要 `PYTORCH_ENABLE_MPS_FALLBACK`。**
接 MPS 只需要改 `backend/app/ai/runtime/workers/tts.py` 的 `_qwen_device()` 一处(加两行,见 §7),
dtype 保持 `float32`(MPS 上 bf16 又慢又不一致,见 §6.2)。

本轮**只做验证**:没有 commit/push,没有改仓库依赖(`pyproject.toml` / `uv.lock` 未动),
没有改产品代码。实验环境全部在仓库外的 `/tmp/qwen-mps-probe/`。

一句话边界:**"听感是否一致"要靠维护者真听两段 wav —— 我没有听过,只做了数值和统计对比。**

---

## 1. 机器与环境

```
system_profiler SPDisplaysDataType
    Chipset Model: Apple M4 Max          # GPU 40 核
    Metal Support: Metal 4
sysctl hw.memsize hw.model
    hw.memsize: 68719476736              # 64 GiB
    hw.model: Mac16,5
sw_vers
    macOS 27.0.1 (Build 26A434), Darwin 27.0.0 arm64
df -h /
    /dev/disk3s1s1  1.8Ti  13Gi  144Gi  9%   # 动手前;venv + 权重就位后还剩 138Gi
```

探针解释器:**Python 3.13.5**(anaconda 的 3.13,`/tmp/qwen-mps-probe/venv`)。
和产品建托管 venv 用的解释器是同一个次版本(3.13)—— 仓库里随包的 `build/python/bin/python3` 是 **3.13.15**
(见 `backend/app/core/interpreter.py: base_python()`),这里差一个 patch 版本,不影响结论。
(后端自己跑 3.14,但引擎 venv 由随包 3.13 建,见同一函数。)

## 2. 装环境(真装,不是看元数据)

```bash
/opt/anaconda3/bin/python3.13 -m venv /tmp/qwen-mps-probe/venv
/tmp/qwen-mps-probe/venv/bin/python -m pip install qwen-tts==0.1.1
```

结果:**成功**(`pip-install.log`;`pip check` → `No broken requirements found`)。真装输出的最后一行:

```
Successfully installed accelerate-1.12.0 ... qwen-tts-0.1.1 soundfile-0.14.0 ... torch-2.14.1 torchaudio-2.11.0 transformers-4.57.3 ...
```

关键版本:

| 包 | 版本 |
|---|---|
| qwen-tts | **0.1.1** |
| torch | **2.14.1**(PyPI macOS arm64 wheel,自带 MPS) |
| torchaudio | 2.11.0 |
| transformers | **4.57.3**(qwen-tts 自己钉的) |
| accelerate | 1.12.0 |
| soundfile / numpy | 0.14.0 / 2.5.4 |

`torch` 的 MPS 探测(用装好 torch 的**那个**环境):

```
$ /tmp/qwen-mps-probe/venv/bin/python -c "import torch; print(torch.__version__, torch.backends.mps.is_available(), torch.backends.mps.is_built())"
2.14.1 True True
```

不致命的噪音(不影响结果,记录在此):import 时 `qwen_tts` 会查系统 `sox` 并打印
`/bin/sh: sox: command not found`(只是它自己的音频工具函数会用到,合成不走它);
以及 `Warning: flash-attn is not installed`(macOS 本来没有 flash-attn,走 manual attention)。

## 3. 权重(钉住 HF commit,逐个核 sha256)

用 HF 上钉住的 commit `0c0e3051f131929182e2c023b9537f8b1c68adfe`,按
`https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice/resolve/<commit>/<file>`
逐个文件下到 `/tmp/qwen-mps-probe/weights/`(13 个文件,**合计 4,520,218,951 B = 4.52 GB**,
和 `qwen_models.MODEL.total_bytes` 一致;实测 HF 平均 ~8.7 MB/s(大文件段 ~9 MB/s),
03:07:57 → 03:16:38,约 8 分 40 秒)。
**没有**用 `latest`。

两个大文件的 sha256 与 `backend/app/ai/runtime/qwen_models.py` 里钉的值**逐字节相同**:

```
$ shasum -a 256 model.safetensors speech_tokenizer/model.safetensors
38b1d5971bdbd982b561cccec982669a53b0537c3cf5e9bd4778ed07bb2f5137  model.safetensors
836b7b357f5ea43e889936a3709af68dfe3751881acefe4ecf0dbd30ba571258  speech_tokenizer/model.safetensors
```

对照仓库里钉的:`38b1d597…` ✓ / `836b7b35…` ✓;大小也逐字节一致
(3,833,402,552 / 682,293,092)。小文件只是存在性/体积核对,与仓库表一致。

## 4. CPU 基线(`device_map="cpu"`,float32)

`qwen-tts 0.1.1` 有现成的 `generate_custom_voice`(与官方 README 完全一致,产品 worker
`run_qwen()` 用的也是它),没有自己发明 API。README 的示例是 CUDA + bfloat16 + flash-attn,
CPU 这边照产品自己的 CPU 路径换成 `cpu` + `float32`:

```python
model = Qwen3TTSModel.from_pretrained("/tmp/qwen-mps-probe/weights",
                                      device_map="cpu", dtype=torch.float32)
wavs, sr = model.generate_custom_voice(
    text="这是一段用于验证的中文语音，包含数字 3.5 和百分之二十。",
    language="Auto",      # 和 qwen_models.language_for("zh") 一致
    speaker="vivian",     # 产品默认音色
)
```

(脚本:`/tmp/qwen-mps-probe/probe.py`;`language` 也正是产品会给中文报的 `Auto`。)

原始输出(`/tmp/qwen-mps-probe/out/cpu.json`,节选):

```json
{
  "device": "cpu", "dtype": "float32", "torch": "2.14.1",
  "load_seconds": 1.428, "load_peak_rss_gib": 9.572,
  "generate_seconds": 12.601,
  "peak_rss_gib": 9.572,
  "wav": "/tmp/qwen-mps-probe/out/qwen-tts_cpu_float32.wav",
  "sample_rate": 24000, "num_samples": 180480, "audio_seconds": 7.52,
  "peak_abs": 0.57542, "rms": 0.126996, "stage": "done", "ok": true
}
```

- 权重加载 1.43 s —— **偏小,因为刚算过 sha256,权重还在 page cache**;冷盘的加载时间没测。
- 峰值 RSS:多次运行在 **9.6–11.2 GiB** 之间(上表这次 9.6;后面三次都是 11.2,
  `/usr/bin/time -l` 的 `maximum resident set size` 最大到 12.0 GB)。规划内存按 **12 GB** 算更稳。
- 生成 7.52 s 音频花 12.6 s(RTF ≈ 1.68,比实时慢)。

## 5. MPS(同权重、同文本、同音色;`device_map="mps"`,float32)

一次就过 —— **没有报错可贴**。`PYTORCH_ENABLE_MPS_FALLBACK` **没有设置**,日志里也没有任何
"not currently supported on the MPS backend … will fall back to run on the CPU" 的告警,
所以**不是靠 CPU 回退跑的**:没有这个环境变量时,未实现的 MPS 算子会直接抛
`NotImplementedError`,而不是悄悄回退;整条路跑完没抛,说明它压根没碰到需要回退的算子。
(设了 `PYTORCH_ENABLE_MPS_FALLBACK=1` 才会打印「… will fall back to run on the CPU」的警告 ——
这里一行都没有,`mps_fallback_env` 记录也是空串。)权重确实在 GPU 上:`param_device: "mps:0"`,
`mps_driver_allocated_gib: 9.16`。

```
$ /tmp/qwen-mps-probe/venv/bin/python probe.py --device mps --dtype float32
```

原始输出(`/tmp/qwen-mps-probe/out/mps.json`,节选):

```json
{
  "device": "mps", "dtype": "float32", "torch": "2.14.1",
  "load_seconds": 2.109, "load_peak_rss_gib": 5.33,
  "generate_seconds": 10.386,
  "peak_rss_gib": 5.33,
  "mps_current_allocated_gib": 7.804, "mps_driver_allocated_gib": 9.164,
  "param_device": "mps:0",
  "wav": "/tmp/qwen-mps-probe/out/qwen-tts_mps_float32.wav",
  "sample_rate": 24000, "num_samples": 145920, "audio_seconds": 6.08,
  "peak_abs": 0.73289, "rms": 0.092324, "stage": "done", "ok": true
}
```

- 第一次生成 10.39 s,第二次同样参数 **6.40 s** → 第一次有 ~4 s 的 MPS kernel 冷启动开销
  (预热里不含一次生成:`warmup()` 对 qwen 只确认权重,不加载模型)。
- 内存:MPS 驱动分配 **9.16 GiB**(unified memory),进程 RSS 只有 5.33 GiB;
  `/usr/bin/time -l` 的 `peak memory footprint` 是 **10.63 GB** —— 比 CPU 的 8.7–8.8 GB 还略高,
  别把"RSS 小"误读成"省内存"。

## 6. 质量对比(数值;听感要维护者听)

两段默认采样(产品默认参数:`generation_config.json` 是 `do_sample=true, temperature=0.9,
top_k=50, top_p=1.0`)的 wav:

| | CPU | MPS |
|---|---|---|
| wav | `/tmp/qwen-mps-probe/out/qwen-tts_cpu_float32.wav` | `/tmp/qwen-mps-probe/out/qwen-tts_mps_float32.wav` |
| 采样率 | 24000 | 24000 |
| 时长 | 7.52 s(180,480 samples) | **6.08 s**(145,920 samples) |
| 峰值 / RMS | 0.575 / 0.127 | 0.733 / 0.092 |
| NaN/Inf、削波 | 0 / 0 | 0 / 0 |
| 静音帧占比(< -60 dBFS) | 9.3% | 10.9% |

同一文本两段音频**时长差 -1.44 s(-19.15%)**。这个差**不是 MPS 算错**,原因是默认路径**采样**:
CPU 与 MPS 的随机数流实现不同(`torch.multinomial`),同 seed 也不会抽到同一串 token。
证据:

1. **同一设备可重复**:CPU 跑两次 md5 相同;MPS 跑两次 md5 相同(各自 run1/run2 完全一致)。
2. **改成完全贪心后两台设备逐样本几乎相同**(见下)。
3. MPS 的 `torch.multinomial` 分布本身没问题:20 万次抽样,CPU/MPS 频率都对得上
   `[0.5, 0.3, 0.15, 0.05]`(MPS:0.4997 / 0.2998 / 0.1497 / 0.0508)。

### 6.1 决定性的等价性测试:完全贪心(do_sample=False + subtalker_dosample=False)

只传 `do_sample=False` 不够 —— `generation_config.json` 里 `subtalker_dosample=true` 仍会让
声学码本继续采样(实测这样两台设备时长都是 6.32 s,但波形最佳对齐后互相关也只有 0.056,
零延迟时 0.012,内容不同)。
把 sub-talker 也关掉之后:

| | CPU `out/qwen-tts_cpu_float32_greedy2.wav` | MPS `out/qwen-tts_mps_float32_greedy2.wav` |
|---|---|---|
| 时长 / 采样点 | 6.08 s / 145,920 | 6.08 s / 145,920 |
| 采样率 | 24000 | 24000 |
| 峰值 / RMS | 0.53003 / 0.089602 | 0.53003 / 0.089602 |
| 文件大小 | 291,884 B | 291,884 B |
| 静音帧占比 | 11.84% | 11.84% |

逐样本比较:**最大差 3.05e-05(= 16-bit PCM 的 1 个 LSB)**;145,920 个样本里只有 **533 个
(0.37%)差 1 个 LSB**,其余完全相同;差值 RMS 1.8e-06。也就是说,**token 序列一致,
解码器数值在 16-bit 量化误差内一致** —— MPS 没有算错。

### 6.2 bf16 在 MPS 上:能跑,但**不一致也更慢**(所以不要用)

同一份权重、完全贪心、`dtype=bfloat16`:`out/qwen-tts_mps_bfloat16_bf16greedy.wav`,
生成 **8.97 s**(比 float32 的 5.97 s 慢),音频 6.80 s(浮点精度变化让贪心选了不同的 token,
与 float32 的 6.08 s 不等价),GPU 分配 4.87 GiB。结论:Mac 上**保持 float32**,
不要照 CUDA 那支去用 bfloat16。

### 6.3 用产品 worker 原码端到端跑了一遍(只 monkeypatch 设备选择)

在**不改仓库**的前提下,把 `backend/app/ai/runtime/workers/tts.py` 当模块 import 进探针 venv,
设 `MOSAEL_QWEN_MODEL_DIR=/tmp/qwen-mps-probe/weights`,调用它自己的 `synthesize()`
(脚本 `/tmp/qwen-mps-probe/worker_probe.py`):

- CPU(产品默认 `_qwen_device()`):`out/worker_cpu.wav`,11.52 s,5.68 s 音频,RSS 11.17 GiB,
  事件流正常(`load → generate → encode`),`engine_reported: "qwen-tts"`;
- MPS(把 `tts._qwen_device` 换成 `lambda: ("mps", torch.float32)`,**其他一行没动**):
  `out/worker_mps.wav`,10.09 s,6.80 s 音频,RSS 5.33 GiB,同样的事件流和 `"qwen-tts"`。

即:产品那条代码路径(`_load` 缓存、`generate_custom_voice`、`_write_wave` 写 16-bit wav、
事件上报)在 MPS 上**整条可用**,不需要额外分支。

## 7. 结论与"要改什么"

**A. 能在 MPS 跑,且(在确定性解码下)结果一致。**

建议的改动只在 `backend/app/ai/runtime/workers/tts.py` 的 `_qwen_device()`(当前 238–252 行),
**加两行代码(外加一行注释)**:

```python
    if torch.cuda.is_available():
        return "cuda:0", torch.bfloat16
    # 新增:Apple Silicon 真机验证通过(2026-10-20, M4 Max / torch 2.14.1 / qwen-tts 0.1.1,
    # 完全贪心下与 CPU 逐样本一致到 1 个 16-bit LSB;默认采样与 CPU 的差异只是随机数流不同)。
    if torch.backends.mps.is_available():
        return "mps", torch.float32
    # CPU 用 float32:...
    return "cpu", torch.float32
```

同时把那句 docstring(「**只在 CUDA 上加速** …MPS …没有验证过 …很慢、偶尔算错」)改掉 ——
本轮实测它既没算错(1 LSB 内一致),也比 CPU 快。`dtype` **保持 float32**,不要给 MPS 用 bf16(§6.2)。

其他:不需要 fallback(`PYTORCH_ENABLE_MPS_FALLBACK` 保持不设);`_pick_device()`
(F5/Fish 用的那个)本来就优先 MPS,只有 qwen 这里是 CUDA-only。

### 速度收益(受控对比:完全贪心、同一段 6.08 s 音频)

| | 生成耗时 | RTF(耗时/音频) |
|---|---|---|
| CPU float32 | 10.31 s | 1.70 |
| MPS float32 | 5.97 s | **0.98** |

**约 1.7× 加速**(不是 10×):1.7B 自回归解码是逐 token 小算子,GPU 的并行优势吃不满。
但它把「比实时慢 70%」变成「基本实时」。第一次生成还要多 ~4 s 的 MPS 冷启动;
如果在意首句延迟,可以在 warmup 里加一次极短文本的生成(可选,不影响正确性)。

### 内存

- CPU:峰值 RSS **9.6–11.2 GiB**(`/usr/bin/time` 最大 12.0 GB);
- MPS:GPU 分配 **9.16 GiB** + 进程 RSS 5.33 GiB,`peak memory footprint` **10.63 GB**。
- 16 GB 的 Mac 会紧(系统 + 其它应用还要占);24 GB 及以上没问题。**这一点没在 16 GB 机器上验过。**

## 8. 拿不准 / 没验的

1. **听感**:两段 wav 都留着,请维护者真听(CPU 与 MPS 默认采样各一段;另有完全贪心的
   一对,数值上等价)。我没有听,不能替这个结论背书。
2. **只在 M4 Max + macOS 27.0.1 + torch 2.14.1 上验过**;M1/M2/M3、老 macOS、以及未来
   torch 版本没验。注意 `qwen_models.PIP_REQUIREMENTS` 只钉了 `qwen-tts==0.1.1`,
   **torch 没钉版本**,以后 torch 升级后 MPS 行为可能变 —— 建议接 MPS 时顺手把 torch 版本
   也钉进这个引擎的依赖(或写进报告的复现条件)。
3. **冷盘加载时间没测**(权重一直在 page cache 里)。
4. CPU 峰值 RSS 多次运行不一致(9.6 vs 11.2 GiB,差异在装载阶段就出现),原因没查;
   按较大值规划。
5. 本机 GPU 是 40 核的 M4 Max;低端 Apple GPU 的绝对速度会低一些(正确性不受影响)。

## 9. 复现材料与清理

全部在仓库外,保留着方便复现(共约 5.7 GB:venv 1.5 GB + 权重 4.2 GB + 输出 3.4 MB):

```
/tmp/qwen-mps-probe/
├── venv/                      # qwen-tts 0.1.1 + torch 2.14.1
├── weights/                   # 钉住 commit 的 13 个文件,sha256 已核
├── probe.py                   # cpu/mps/贪心/bf16 探针(--device/--dtype/--greedy)
├── worker_probe.py            # 用产品 worker 原码端到端(np cpu|mps)
├── compare.py                 # wav 统计(时长/采样率/峰值/RMS/静音/NaN/频谱质心)
├── env-probe.log              # 机器、torch/MPS、pip freeze 原始输出
├── pip-install.log            # 真装日志
├── download.sh                # 按钉住 commit 下权重的脚本
└── out/
    ├── cpu.json / cpu_run2.json            # CPU 默认采样 ×2(md5 相同)
    ├── mps.json / mps_run2.json            # MPS 默认采样 ×2(md5 相同)
    ├── cpu_greedy.json / mps_greedy.json     # 只关 talker 采样(内容不同,见 §6.1)
    ├── cpu_greedy2.json / mps_greedy2.json # 完全贪心(逐样本等价)
    ├── mps_bf16greedy.json                 # MPS bf16(不一致也更慢)
    ├── worker_cpu.json / worker_mps.json   # 产品 worker 端到端
    └── *.wav                               # 上面每个 json 对应的音频
```

磁盘还够(`df -h /`:138 GiB 可用),所以没清。要复现最省事的两条:

```bash
/tmp/qwen-mps-probe/venv/bin/python /tmp/qwen-mps-probe/probe.py --device mps --dtype float32 --greedy --tag check
/tmp/qwen-mps-probe/venv/bin/python /tmp/qwen-mps-probe/probe.py --device cpu --dtype float32 --greedy --tag check
```
