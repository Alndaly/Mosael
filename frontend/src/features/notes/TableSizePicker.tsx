import React from "react";

import { isImeKeystroke } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";
import { useNoteStrings } from "./strings";

/**
 * 插入表格的格子选择器(Word、Google Docs 那种):指针移到哪一格,从左上角到那一格都亮起来,下面写着「3 × 4」(行 × 列);
 * 点下去就插入这么大的表格。
 *
 * - **大小**:一打开是 8 × 8;移到最后一行 / 一列时往外再长一格,最多 10 × 10。往回移又缩回去。
 * - **键盘**:方向键挪(焦点跟着那一格走,只有它在 Tab 序列里),回车插入;Esc 由外面那层浮层收起。
 * - **读屏**:整块是一张叫「插入表格」的 grid,每一格的名字就是它代表的大小。
 *
 * 行数算上表头那一行,和此前直接插入的 3 × 3 一样(表头 + 两行)。
 */

export type TableSize = { rows: number; cols: number };

const BASE = 8;
const MAX = 10;

/** 摆出几行几列:放得下指着的那一格、再多一格好接着往外移;不少于 BASE,不多于 MAX。 */
export function tableGridSize(at: TableSize): TableSize {
  const fit = (n: number) => Math.min(MAX, Math.max(BASE, n + 1));
  return { rows: fit(at.rows), cols: fit(at.cols) };
}

const STEP: Record<string, [number, number]> = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };

export function TableSizePicker({ onPick, autoFocus }: {
  onPick: (size: TableSize) => void;
  /** 挂上就把焦点放进来(「更多格式」菜单里就地展开时用;单独的浮层由浮层自己把焦点放进来)。 */
  autoFocus?: boolean;
}) {
  const s = useNoteStrings();
  const [at, setAt] = React.useState<TableSize>({ rows: 1, cols: 1 });
  const grid = tableGridSize(at);
  const cells = React.useRef(new Map<string, HTMLButtonElement>());
  const key = (size: TableSize) => `${size.rows}x${size.cols}`;
  React.useEffect(() => { if (autoFocus) cells.current.get(key({ rows: 1, cols: 1 }))?.focus(); }, [autoFocus]);

  return (
    <div className="grid justify-items-center gap-2">
      <div
        role="grid"
        aria-label={s.insertTable}
        className="flex flex-col gap-[3px]"
        onKeyDown={(event) => {
          if (isImeKeystroke(event)) return;
          if (event.key === "Enter") {
            event.preventDefault();
            onPick(at);
            return;
          }
          const step = STEP[event.key];
          if (!step) return;
          event.preventDefault();
          const next = {
            rows: Math.min(MAX, Math.max(1, at.rows + step[0])),
            cols: Math.min(MAX, Math.max(1, at.cols + step[1])),
          };
          setAt(next);
          //: 下一格一定已经摆着:网格总比指着的那一格多出一行一列(到 MAX 为止),所以这里就能把焦点挪过去。
          cells.current.get(key(next))?.focus();
        }}
      >
        {Array.from({ length: grid.rows }, (_, r) => (
          <div key={r} role="row" className="flex gap-[3px]">
            {Array.from({ length: grid.cols }, (_, c) => {
              const size = { rows: r + 1, cols: c + 1 };
              const lit = size.rows <= at.rows && size.cols <= at.cols;
              return (
                <button
                  key={c}
                  ref={(node) => { if (node) cells.current.set(key(size), node); else cells.current.delete(key(size)); }}
                  type="button"
                  role="gridcell"
                  aria-label={s.tableSize(size.rows, size.cols)}
                  aria-selected={lit}
                  tabIndex={size.rows === at.rows && size.cols === at.cols ? 0 : -1}
                  className={cn(
                    "size-[18px] rounded-[3px] border outline-none transition-colors motion-reduce:transition-none",
                    "focus-visible:ring-2 focus-visible:ring-ring",
                    lit ? "border-primary/60 bg-primary/15" : "border-input/40 bg-field",
                  )}
                  onMouseEnter={() => setAt(size)}
                  onFocus={() => setAt(size)}
                  onClick={() => onPick(size)}
                />
              );
            })}
          </div>
        ))}
      </div>
      <div aria-hidden className="text-ui-xs tabular-nums text-muted-foreground">{s.tableSize(at.rows, at.cols)}</div>
    </div>
  );
}
