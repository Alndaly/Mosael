"""子进程的**最后一行**不是失败原因。这一条已经踩过三次。

- 合成失败,取到 `[end of libtorchcodec loading traceback].` —— 一条分隔线;
- 装依赖失败,取到 ``note: run with `RUST_BACKTRACE=1` ...`` —— 一句纯提示;
- 下载权重失败,取到 `Downloading: 100%|██████| 1/1 [00:00<00:00, 1.39file/s]` ——
  一根**进度条**(huggingface_hub 的 tqdm 写在 stderr 上,下完就停在那儿)。

三次都让用户对着一句和病因毫无关系的话发愣,第三次还配了个点不动的「重试」。判据因此收进
`core/text.blame_line` 一处,这里钉的是"三条路都用它"。
"""
from __future__ import annotations

import pytest

from app.ai.runtime.tts_models import _explain_failure
from app.domain.voices.voices import explain_worker_failure
from app.core.text import blame_line

#: 真机上那一次(0.18.1,Windows):卡片上的红字就是这根进度条。
PROGRESS_ONLY = (
    "Fetching 1 files:   0%|          | 0/1 [00:00<?, ?it/s]\r"
    "Downloading: 100%|██████████| 1/1 [00:00<00:00, 1.39file/s]"
)


def test_a_progress_bar_is_never_the_reason() -> None:
    assert blame_line(PROGRESS_ONLY) == "", "进度条被当成了失败原因"


def test_the_real_error_above_the_progress_bar_wins() -> None:
    """进度条在后、真错误在前 —— 取最后一行必然取错。"""
    text = "OSError: Consistency check failed for model.safetensors\n" + PROGRESS_ONLY
    assert blame_line(text) == "OSError: Consistency check failed for model.safetensors"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # 第一次发作:torchcodec 以自己的分隔线收尾。
        ("ImportError: libavutil.so.59 not found\n[end of libtorchcodec loading traceback].",
         "ImportError: libavutil.so.59 not found"),
        # caret 行是终端里指出错列的记号,到了浏览器只是噪声。
        ("  data = f(x)\n         ^^^^^^\nValueError: nope", "ValueError: nope"),
        # traceback 的位置行说不出原因。
        ('Traceback (most recent call last):\n  File "a.py", line 3, in f\nKeyError: \'k\'',
         "KeyError: 'k'"),
        # 一句纯提示不是结论。
        ("ERROR: Could not build wheels for rjieba\nnote: run with `RUST_BACKTRACE=1`",
         "ERROR: Could not build wheels for rjieba"),
    ],
)
def test_the_noisy_tails_are_skipped(text: str, expected: str) -> None:
    assert blame_line(text) == expected


def test_nothing_to_say_is_said_plainly_not_papered_over() -> None:
    """说不出原因时给一句能行动的话,而**不是**把进度条或整段原文端出去。

    这里的坑在 fallback:第一版把 fallback 写成了原文,于是输出全是进度条时,
    "挑不出结论"又变回了"把进度条端出去" —— 等于没修。
    """
    for explain in (_explain_failure, explain_worker_failure):
        message = explain(PROGRESS_ONLY)
        assert "没有留下原因" in message, f"{explain.__name__} 没说清「说不出原因」"
        assert "100%" not in message and "file/s" not in message, f"{explain.__name__} 把进度条端出去了"


def test_both_paths_still_surface_a_real_error() -> None:
    """别为了滤噪声把真话也滤掉。"""
    text = "ModuleNotFoundError: No module named 'natsort'\n" + PROGRESS_ONLY
    assert "natsort" in _explain_failure(text)
    assert "natsort" in explain_worker_failure(text)


def test_an_error_sharing_a_line_with_the_bar_comes_back_clean() -> None:
    """tqdm 用 `\\r` 在**同一行**里反复重画,后面的输出常常就接在最后一帧屁股上。

    不按 `\\r` 拆的话,挑出来的"那一行"会拖着半根进度条 —— 报错读起来像
    `Downloading: 100%|████| 1/1 [00:00<00:00, 1.39file/s]OSError: boom`。
    """
    line = "Downloading:  50%|█████     | 0/1 [00:00<?, ?it/s]\rOSError: Consistency check failed"
    assert blame_line(line) == "OSError: Consistency check failed"
