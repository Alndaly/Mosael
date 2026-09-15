from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app


def main() -> None:
    out = ROOT / "openapi.json"
    current = json.dumps(app.openapi(), ensure_ascii=False, indent=2)
    #: --check 是 CI 的门:提交的快照必须是 app 此刻的真实形状。只在发版前或想得起来
    #: 的时候才再生成的话,路由和前端 schema.d.ts 之间的漂移没有任何东西会喊停。
    if "--check" in sys.argv:
        if out.read_text(encoding="utf-8") != current:
            print(f"{out} 已过期 —— 跑 scripts/export_openapi.py 再生成,然后 pnpm gen:api")
            raise SystemExit(1)
        print(f"{out} 是最新的")
        return
    out.write_text(current, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
