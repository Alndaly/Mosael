"""demucs 分离 Adapter —— 契约的本地实现。

它**不自己跑模型**:分离跑在 `ai/runtime/workers/separation.py` 里,由这个引擎自己那个 venv
的解释器起成子进程。这个文件只做三件事:说自己现在跑不跑得起来、把环境准备好、把一次请求
翻成那个子进程的输入输出。

为什么要出进程,而不是在后端进程里 `import demucs`:torch 会把后端进程撑大一个数量级,
而且它和转写/克隆各自钉的 torch 版本会打架 —— 那正是 asr 和 tts 各有一个 venv 的原因。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

from app.core.child_process import run_logged

from app.ai.providers.contracts.separation import (
    SEPARATION_TIMEOUT_SECONDS,
    SeparationError,
    SeparationRequest,
)
from app.ai.runtime import separation_models, workers

logger = logging.getLogger(__name__)


class DemucsSeparationAdapter:
    """htdemucs,本地跑。"""

    engine_id = "demucs"
    label_key = "sepEngine_demucs"

    def runtime_ready(self) -> bool:
        return separation_models.runtime_ready(self.engine_id)

    def ensure_runtime(self) -> None:
        separation_models.ensure_runtime(self.engine_id)

    def separate(self, request: SeparationRequest, out_dir: Path) -> dict[str, Path]:
        python = separation_models.managed_venv_python(self.engine_id)
        if not python.is_file():
            raise SeparationError("音频分离的运行环境还没准备好")
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "audio_path": str(request.audio_path),
            "out_dir": str(out_dir),
            "model": separation_models.DEFAULT_MODEL,
            "stems": list(request.stems),
        }
        # 结果写文件而不是读 stdout:demucs 和 torch 把进度条和警告直接打在 stdout 上
        # (asr worker 为同一个原因这么做)。
        with tempfile.NamedTemporaryFile("r", suffix=".json", delete=False) as handle:
            result_path = Path(handle.name)
        env = dict(os.environ)
        # 权重落在应用自己的数据目录,不是用户主目录 —— 卸载时有一个地方可以整个删掉。
        env["TORCH_HOME"] = str(separation_models.TORCH_HOME)
        try:
            #: 外部命令只从 run_logged 这一个口子出去 —— 它记命令、记耗时,失败时带上
            #: 子进程自己说的那句话(此前 35 个裸 subprocess.run 各自是黑箱)。
            completed = run_logged(
                [str(python), str(workers.separation_script()), str(result_path)],
                what="音频分离",
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=SEPARATION_TIMEOUT_SECONDS,
                env=env,
            )
            if completed.returncode != 0:
                tail = (completed.stderr or completed.stdout or "").strip().splitlines()
                raise SeparationError(tail[-1] if tail else f"分离失败(退出码 {completed.returncode})")
            try:
                produced = json.loads(result_path.read_text(encoding="utf-8")).get("stems") or {}
            except (OSError, ValueError) as exc:
                raise SeparationError(f"分离结果读不出来:{exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise SeparationError("分离超时") from exc
        finally:
            result_path.unlink(missing_ok=True)

        stems = {name: Path(path) for name, path in produced.items()}
        missing = [name for name in request.stems if name not in stems or not stems[name].is_file()]
        if missing:
            # **少给一条就报错,不静默返回半份** —— 少的那条会一路空到成片里。
            raise SeparationError(f"分离结果里缺少:{'、'.join(missing)}")
        return stems
