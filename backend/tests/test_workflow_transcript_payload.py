from __future__ import annotations

import json

from app.domain.workflows.executors.subjobs import _compact_timed_text


def test_compact_timed_text_keeps_precise_tokens_without_repeating_token_keys() -> None:
    segments = [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "你好",
            "speaker": "",
            "tokens": [
                {"start": 0.12, "end": 0.4, "text": "你"},
                {"start": 0.52, "end": 0.8, "text": "好"},
            ],
        },
        {"start": 2.0, "end": 3.0, "text": "欢迎", "speaker": "S1", "tokens": []},
    ]

    encoded = _compact_timed_text(segments)

    assert json.loads(encoded) == {
        "token_columns": ["start", "end", "text"],
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "你好", "tokens": [[0.12, 0.4, "你"], [0.52, 0.8, "好"]]},
            {"start": 2.0, "end": 3.0, "speaker": "S1", "text": "欢迎"},
        ],
    }
    verbose = json.dumps(segments, ensure_ascii=False, separators=(",", ":"))
    assert encoded.count('"start"') == len(segments) + 1  # 每段一次 + token_columns 一次
    assert verbose.count('"start"') == len(segments) + 2  # 旧格式还会在每个 token 重复
    assert '"speaker":""' not in encoded
