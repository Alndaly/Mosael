"""重新生成 `tests/migration_bodies.json`。

`python -m tests.freeze_migration_bodies`(在 backend/ 里跑)。

**它不是「让测试变绿」的按钮。** 指纹变了通常说明一个已经记过账的一次性迁移被改了身体,
而那对已经升过的机器无效 —— 正确做法是新开一个步骤名。只有确属无害的重构(纯改名、
换等价写法)才该跑这个脚本,并在提交信息里说明为什么结果不变。
"""

from __future__ import annotations

import json

from tests.test_migration_bodies_are_frozen import FINGERPRINTS, _fingerprints


def main() -> None:
    FINGERPRINTS.write_text(
        json.dumps(dict(sorted(_fingerprints().items())), indent=2) + "\n", encoding="utf-8"
    )
    print(FINGERPRINTS)


if __name__ == "__main__":
    main()
