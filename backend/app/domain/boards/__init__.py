"""创意画板领域。

- `canvas` —— 画布的形状、读写、版本、回执(产出填回那一格);
- `ops` —— 智能体用的细粒度编辑算子;
- `actions` —— 画板上的四个动作(生成、写字、念出来、截一段);
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
    place_pending,
    receipt_to_item,
    set_text_write_run,
    update_board,
    write_text,
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
    "place_pending",
    "receipt_to_item",
    "set_text_write_run",
    "update_board",
    "write_text",
]
