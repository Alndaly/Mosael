"""创意画板:一张无限画布,用来攒想法。

除了和智能体对话之外的另一条路 —— 对话是线性的,而想法不是。画板让人把碎片摊开、挪动、
连起来,先看见结构再决定做什么。

## 这一层负责什么

**画布的形状**。数据库那边只有一列 JSON(见 db/models.Board),什么算合法的画布由这里说了算。
校验放在领域层而不是路由:画板将来会有第二个入口(智能体往板上贴东西、工作流产出落到板上),
放在路由里就意味着那些入口各自再写一遍,而漏掉的那一遍不会报错 —— 只会存进一张打不开的板。

## 为什么校验得这么紧

存进去的东西下一次是**要渲染**的。一个坐标是字符串、一个 kind 拼错了,前端拿到的是一张
渲染到一半崩掉的画布,而错误发生在几天前的某一次保存里。所以宁可在写入时就拒绝:
拒绝的那一刻用户还知道自己刚做了什么。

## 拆成了几块

这个模块本身只是入口,代码按职责住在同一个包的几个子模块里:

- `errors` —— 画板领域的错误;
- `shape` —— 画布的形状与上限、`normalize_canvas`;
- `validation` —— 引用校验、`check_canvas`;
- `persistence` —— 读写、版本、复制、比较并交换的保存;
- `run_state` —— 运行态归服务端(`live_job`、`_keep_server_owned_state`);
- `outputs` —— 产出怎么落到画布上(纯函数);
- `receipts` —— 摆占位、服务端单格合并、回执。
"""

from __future__ import annotations

# 重新导出:外面(路由、智能体、测试)一直从 app.domain.boards.canvas 取这些名字(含私有的),拆分后入口不变。
from app.domain.boards.errors import (
    BoardDomainError,
    BoardNotFound,
    BoardRevisionConflict,
    _field_error,
    item_not_found,
)
from app.domain.boards.outputs import (
    MAX_DERIVED_ITEMS,
    OUTPUT_TYPES,
    _DERIVED_GAP_X,
    _DERIVED_GAP_Y,
    _GRID_GAP_IN_ROW,
    _GRID_TILE_WIDTH,
    _canvas_with_delivered_result,
    _clip,
    _derive,
    _derived_item,
    _fits,
    _grid_tile_size,
    _json_text,
    _overflow_value,
    outputs_of,
)
from app.domain.boards.persistence import (
    _copy_timelines,
    board_project,
    create_board,
    delete_board,
    duplicate_board,
    ensure_revision,
    get_board,
    list_boards,
    update_board,
)
from app.domain.boards.receipts import (
    RECEIPT_KIND,
    _MERGE_ATTEMPTS,
    _asset_facts,
    _deliver_if_already_settled,
    _keeping_abilities,
    _merge_into_latest,
    _with_ability,
    deliver_generated,
    install,
    place_pending,
    receipt_to_item,
)
from app.domain.boards.run_state import (
    _keep_server_owned_state,
    live_job,
)
from app.domain.boards.shape import (
    DEFAULT_SIZE,
    ITEM_KINDS,
    MAX_ITEMS,
    MAX_TEXT_CHARS,
    MAX_TITLE_CHARS,
    NOTE_COLORS,
    RUN_STATUSES,
    TEXT_FORMATS,
    _ABILITY_KEYS,
    _MEDIA_KINDS,
    _REQUIRED,
    _attached,
    _check_config,
    _drop_detached_bindings,
    _normalize_abilities,
    _normalize_bindings,
    _normalize_form,
    _normalize_run,
    _normalize_source,
    _normalize_title,
    _normalize_trim,
    finite_number,
    normalize_canvas,
)
from app.domain.boards.validation import (
    _ASSET_KIND_OF_ITEM,
    _validate_asset_references,
    _validate_references,
    check_canvas,
)

__all__ = [
    "BoardDomainError",
    "BoardNotFound",
    "BoardRevisionConflict",
    "DEFAULT_SIZE",
    "ITEM_KINDS",
    "MAX_DERIVED_ITEMS",
    "MAX_ITEMS",
    "MAX_TEXT_CHARS",
    "MAX_TITLE_CHARS",
    "NOTE_COLORS",
    "OUTPUT_TYPES",
    "RECEIPT_KIND",
    "RUN_STATUSES",
    "TEXT_FORMATS",
    "_ABILITY_KEYS",
    "_ASSET_KIND_OF_ITEM",
    "_DERIVED_GAP_X",
    "_DERIVED_GAP_Y",
    "_GRID_GAP_IN_ROW",
    "_GRID_TILE_WIDTH",
    "_MEDIA_KINDS",
    "_MERGE_ATTEMPTS",
    "_REQUIRED",
    "_asset_facts",
    "_attached",
    "_canvas_with_delivered_result",
    "_check_config",
    "_clip",
    "_copy_timelines",
    "_deliver_if_already_settled",
    "_derive",
    "_derived_item",
    "_drop_detached_bindings",
    "_field_error",
    "_fits",
    "_grid_tile_size",
    "_json_text",
    "_keep_server_owned_state",
    "_keeping_abilities",
    "_merge_into_latest",
    "_normalize_abilities",
    "_normalize_bindings",
    "_normalize_form",
    "_normalize_run",
    "_normalize_source",
    "_normalize_title",
    "_normalize_trim",
    "_overflow_value",
    "_validate_asset_references",
    "_validate_references",
    "_with_ability",
    "board_project",
    "check_canvas",
    "create_board",
    "delete_board",
    "deliver_generated",
    "duplicate_board",
    "ensure_revision",
    "finite_number",
    "get_board",
    "install",
    "item_not_found",
    "list_boards",
    "live_job",
    "normalize_canvas",
    "outputs_of",
    "place_pending",
    "receipt_to_item",
    "update_board",
]
