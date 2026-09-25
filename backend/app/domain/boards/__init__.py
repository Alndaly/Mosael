"""创意画板领域。

- `canvas` —— 画布的形状、读写、版本、回执(产出填回那一格);
- `ops` —— 智能体用的细粒度编辑算子;
- `producers` —— 画板上的产出者注册表:一切产出都从 `producers.run` 进(ADR 0021);
- `actions` —— 四个内置产出者的本体(生成、写字、念出来、截一段);
- `trim` —— 截一段的任务本体。
"""

from app.domain.boards.canvas import (
    ITEM_KINDS,
    MAX_ITEMS,
    MAX_TEXT_CHARS,
    NOTE_COLORS,
    RECEIPT_KIND,
    RUN_STATUSES,
    BoardDomainError,
    BoardNotFound,
    BoardRevisionConflict,
    check_canvas,
    create_board,
    delete_board,
    deliver_generated,
    duplicate_board,
    ensure_revision,
    finite_number,
    get_board,
    install,
    list_boards,
    normalize_canvas,
    outputs_of,
    place_pending,
    receipt_to_item,
    update_board,
)

__all__ = [
    "ITEM_KINDS",
    "MAX_ITEMS",
    "MAX_TEXT_CHARS",
    "NOTE_COLORS",
    "RECEIPT_KIND",
    "RUN_STATUSES",
    "BoardDomainError",
    "BoardNotFound",
    "BoardRevisionConflict",
    "check_canvas",
    "create_board",
    "delete_board",
    "deliver_generated",
    "duplicate_board",
    "ensure_revision",
    "finite_number",
    "get_board",
    "install",
    "list_boards",
    "normalize_canvas",
    "outputs_of",
    "place_pending",
    "receipt_to_item",
    "update_board",
]
