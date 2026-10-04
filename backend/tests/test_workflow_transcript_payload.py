from __future__ import annotations

import json

from app.domain.workflows.executors.subjobs import _compact_timed_text


def test_compact_timed_text_gives_paragraphs_and_the_words_around_pauses_only() -> None:
    """段落级起止和正文;词级时间只在段内长停顿两边给(整份词级时间在长素材上撑爆上下文)。"""
    segments = [
        {
            "start": 0.0,
            "end": 3.0,
            "text": "你好,嗯,欢迎",
            "speaker": "",
            "tokens": [
                {"start": 0.12, "end": 0.4, "text": "你"},
                {"start": 0.52, "end": 0.8, "text": "好"},
                {"start": 1.9, "end": 2.1, "text": "嗯"},
                {"start": 2.2, "end": 2.5, "text": "欢"},
                {"start": 2.6, "end": 2.9, "text": "迎"},
            ],
        },
        {"start": 3.0, "end": 4.0, "text": "谢谢", "speaker": "S1",
         "tokens": [{"start": 3.1, "end": 3.4, "text": "谢"}, {"start": 3.5, "end": 3.8, "text": "谢"}]},
    ]

    encoded = _compact_timed_text(segments)

    assert json.loads(encoded) == {
        "token_columns": ["start", "end", "text"],
        "segments": [
            {"start": 0.0, "end": 3.0, "text": "你好,嗯,欢迎", "pauses": [[0.8, 1.9]],
             "tokens": [[0.12, 0.4, "你"], [0.52, 0.8, "好"], [1.9, 2.1, "嗯"], [2.2, 2.5, "欢"]],
             #: 口头禅候选另给一份起止(不管在不在停顿附近,见 test_cleanup_gives_fillers_their_times)。
             "fillers": [[1.9, 2.1, "嗯"]]},
            {"start": 3.0, "end": 4.0, "speaker": "S1", "text": "谢谢"},
        ],
    }
    assert '"speaker":""' not in encoded
