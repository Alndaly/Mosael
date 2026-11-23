"""工作流节点定义(`node_types.NODE_TYPES`)的形状:节点上能写哪些键、配置字段上能写哪些键。

此前是 `dict[str, dict[str, Any]]`:95 个节点、21 个节点级键、28 个字段级键,37 个模块按字符串去读。执行器那一侧有锁步测试,
元数据这一侧打错一个键名(`"advnced": True`)不会报错,只会让界面上那一格默默不生效。现在键在这里列全,
tests/test_node_specs_use_declared_keys 钉住「每个节点、每个字段只用这里声明过的键」。

各键的含义与规矩写在 `node_types.NODE_TYPES` 上方那一大段说明里;这里只列名字、类型和一句话。
"""

from __future__ import annotations

from typing import Any, Required, TypedDict


class FieldSpec(TypedDict, total=False):
    """节点配置里的一格。"""

    #: 值的种类(string / number / boolean / object / list / select / text……),决定默认控件。
    type: Required[str]
    #: 说明的文案 key;`description_params` 是填进去的参数(生成出来的那几段,如素材角色说明)。
    description: str
    description_params: dict[str, str]
    #: 显示名的文案 key(不给就按字段名生成)。
    label: str
    #: 专用控件(不用 `type` 的默认控件)。
    editor: str
    #: 不单独出一格,由这一格的控件一起编辑。
    edited_by: str
    #: 参数表控件同时编辑的那两格:必填清单、各参数的取值清单。
    required_list: str
    options_map: str
    required: bool
    #: 收进「高级」里。
    advanced: bool
    default: Any
    #: 闭集选项;或者由后端现查(`options_from`,`depends_on` 的值作为 parent 带上);`allow_custom` 允许写清单外的值。
    options: list[str]
    options_from: str
    depends_on: str
    allow_custom: bool
    #: 留空 = 清单里只有一项时用那一项,多于一项时运行时报出来。
    sole_option_default: bool
    #: 只在别的字段取某些值时才出现(见 field_activation)。
    active_when: dict[str, Any]
    #: 收哪种素材(image / video / audio……),给素材选择器用。
    media: str | list[str]
    #: 这一格在画布上作为数据口的类型。
    data_type: str
    #: 一行一项的列表;每一项叫什么从哪里取。
    lines: bool
    entry_labels: str
    #: 提示词里引用到的图以「参考图」并进哪一格、用什么角色、由哪道能力闸放行。
    ref_assets_from: list[str]
    ref_assets_role: str
    ref_assets_gate: str
    #: `{{…}}` 引用怎么代入(见 workflows.binding)。
    interpolate: str
    #: 同组的字段恰好填一个;`one_of_strict` 时不按顺序兜底。
    one_of: str
    one_of_strict: bool
    #: 画板上这一项只挂在宿主格上(参数,不是宿主,见 boards.transforms)。
    board_host: bool


class NodeSpec(TypedDict, total=False):
    """一种工作流节点。"""

    #: 交给外部执行器跑(而不是进程内)。
    external: Required[bool]
    #: 会不会用到某人的 AI 供应商连接或插件连接(ADR 0047)。
    spends: Required[bool]
    category: Required[str]
    label: Required[str]
    description: Required[str]
    config: Required[dict[str, FieldSpec]]
    outputs: Required[list[str]]
    #: 各输出的显示名、数据类型、媒体种类。
    output_labels: dict[str, str]
    output_types: dict[str, str]
    output_media: dict[str, Any]
    #: 输出的形状由哪一格配置决定(见 node_catalog)。
    output_schema_from: dict[str, str]
    #: 按配置逐项展开的输出(「输出」节点的每一项具名输出)。
    port_maps: dict[str, dict[str, Any]]
    #: 只在这几处出现(画板、工作流……)。
    surfaces: list[str]
    #: 画板上:交出哪几个输出、归哪一组、一句说明、交出列数的那个输出。
    board_outputs: list[str]
    board_group: str
    board_description: str
    board_columns: str
    #: 连线用的输出(和交给画板的不同时)。
    wiring_outputs: list[str]
    #: 条件分支的出口。
    branches: list[str]
    #: 循环 / 子图节点的体内作用域。
    body_scope: dict[str, list[str]]
    #: 副作用的种类(见 domain/effects)。
    effects: str
