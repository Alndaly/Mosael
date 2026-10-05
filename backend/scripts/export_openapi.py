from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.node_catalog import describe_node_types

#: 内置节点类型的接点快照:每种节点的配置字段(类型、编辑器、按什么单位接线)和声明的输出,连同**两种语言的名字**。
#: 前端画布的测试拿它当注册表 ——「每种节点、按声明能接上游的字段,卡片上都有那个输入口;官方模板里每条数据边两头的口
#: 都在」(防 React Flow 008:线指向一个卡片没画的口,整根线消失),以及「每个口在中英文界面上都叫一个人话名字、同一侧
#: 不撞名」(portsHaveHumanNames)。节点目录只在后端,前端测试不另抄一份。
NODE_PORTS = ROOT.parent / "frontend" / "src" / "api" / "generated" / "workflow-node-ports.json"

#: 快照里留的字段声明:决定一处引用落在哪个口、那个口叫什么的那几项(见前端 workflows/portNames)。
_PORT_SPEC_FIELDS = ("type", "editor", "lines", "entry_labels")
_LOCALES = ("zh", "en")


def node_ports() -> str:
    described = {locale: {item["type"]: item for item in describe_node_types(NODE_TYPES, locale)} for locale in _LOCALES}
    ports = [
        {
            "type": node_type,
            "config": {
                key: {
                    **{field: spec[field] for field in _PORT_SPEC_FIELDS if field in spec},
                    "label": {locale: described[locale][node_type]["config"][key]["label"] for locale in _LOCALES},
                }
                for key, spec in item["config"].items()
            },
            "outputs": item["outputs"],
            "output_labels": {
                output: {locale: described[locale][node_type]["output_labels"][output] for locale in _LOCALES}
                for output in item["outputs"]
            },
            **({"port_maps": item["port_maps"]} if item.get("port_maps") else {}),
            #: 循环 / 子图体内看得见的作用域:体里那几格(body / output / condition)的引用属于体,不是这一层的口。
            **({"body_scope": item["body_scope"]} if item.get("body_scope") else {}),
        }
        for node_type, item in sorted(described["zh"].items())
    ]
    return json.dumps(ports, ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    out = ROOT / "openapi.json"
    current = json.dumps(app.openapi(), ensure_ascii=False, indent=2)
    ports = node_ports()
    #: --check 是 CI 的门:提交的快照必须是 app 此刻的真实形状。只在发版前或想得起来
    #: 的时候才再生成的话,路由和前端 schema.d.ts 之间的漂移没有任何东西会喊停。
    if "--check" in sys.argv:
        stale = False
        if out.read_text(encoding="utf-8") != current:
            print(f"{out} 已过期 —— 跑 scripts/export_openapi.py 再生成,然后 pnpm gen:api")
            stale = True
        if not NODE_PORTS.exists() or NODE_PORTS.read_text(encoding="utf-8") != ports:
            print(f"{NODE_PORTS} 已过期 —— 跑 scripts/export_openapi.py 再生成")
            stale = True
        if stale:
            raise SystemExit(1)
        print(f"{out} 和 {NODE_PORTS.name} 是最新的")
        return
    out.write_text(current, encoding="utf-8")
    NODE_PORTS.write_text(ports, encoding="utf-8")
    print(out)
    print(NODE_PORTS)


if __name__ == "__main__":
    main()
