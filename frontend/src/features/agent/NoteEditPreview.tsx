import React from "react";

import { useI18n } from "@/app/preferences";
import { diffText, type DiffSegment } from "@/features/agent/textDiff";
import { cn } from "@/lib/utils";

/**
 * 改笔记(edit_note)确认卡上的「要改什么」:每个操作一块。
 *
 * 通用参数表把 operations 画成一块 JSON —— 长文本挤在一行里、换行是字面的 `\n`,而这张卡上用户要批的
 * 恰恰是「这段字会变成什么样」。所以这里照操作画:替换是原文 → 新文的差异(删去的划掉、新加的高亮,
 * 没变的照常),插入是锚点那一截上下文加要插进去的字。原始 JSON 仍在卡底的「原始数据」里。
 */
export function NoteEditPreview({ payload }: { payload: Record<string, unknown> }) {
  const operations = Array.isArray(payload.operations) ? payload.operations : [];
  return (
    <ol className="m-0 grid min-w-0 list-none gap-2 p-0">
      {operations.map((operation, index) => (
        <li key={index} className="min-w-0">
          <OperationBlock operation={(operation ?? {}) as Operation} />
        </li>
      ))}
    </ol>
  );
}

type Operation = { kind?: string; find?: string; text?: string; after?: string; before?: string };

/** 插入时露出的锚点上下文有多长:够认出是哪一处,又不把整段搬上卡。 */
const ANCHOR_CONTEXT = 40;
/** 折起时露出多少字。 */
const FOLD_CHARS = 400;

function OperationBlock({ operation }: { operation: Operation }) {
  const t = useI18n();
  const text = typeof operation.text === "string" ? operation.text : "";
  let label: string;
  let segments: DiffSegment[];
  if (operation.kind === "replace") {
    label = text ? t("confirmNoteReplace") : t("confirmNoteDelete");
    segments = diffText(String(operation.find ?? ""), text);
  } else if (operation.after) {
    label = t("confirmNoteInsertAfter");
    segments = [{ kind: "same", text: `…${operation.after.slice(-ANCHOR_CONTEXT)}` }, { kind: "ins", text }];
  } else {
    label = t("confirmNoteInsertBefore");
    segments = [{ kind: "ins", text }, { kind: "same", text: `${String(operation.before ?? "").slice(0, ANCHOR_CONTEXT)}…` }];
  }
  return (
    <div className="grid min-w-0 gap-1" data-note-op={operation.kind === "replace" ? "replace" : "insert"}>
      <span className="text-ui-xs text-muted-foreground">{label}</span>
      <Segments segments={segments} />
    </div>
  );
}

/** 差异正文。长的先露前 FOLD_CHARS 字(按段截,截到哪段就停在哪段),底下一条展开。 */
function Segments({ segments }: { segments: DiffSegment[] }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const total = segments.reduce((sum, one) => sum + one.text.length, 0);
  const folded = total > FOLD_CHARS;
  const shown = open || !folded ? segments : clip(segments, FOLD_CHARS);
  return (
    <div className="min-w-0 overflow-hidden rounded-md border border-border bg-panel-inset">
      <p className="m-0 whitespace-pre-wrap p-2.5 text-ui-xs leading-[1.65] [overflow-wrap:anywhere]">
        {shown.map((one, index) =>
          one.kind === "del" ? (
            <del key={index} className="rounded-sm bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] text-destructive line-through">
              {one.text}
            </del>
          ) : one.kind === "ins" ? (
            <ins key={index} className="rounded-sm bg-[color-mix(in_srgb,var(--success)_16%,transparent)] text-foreground no-underline">
              {one.text}
            </ins>
          ) : (
            <span key={index} className="text-muted-foreground">{one.text}</span>
          ),
        )}
        {folded && !open ? <span className="text-muted-foreground">…</span> : null}
      </p>
      {folded ? (
        <button
          type="button"
          aria-expanded={open}
          className={cn(
            "flex w-full cursor-pointer items-center justify-center border-0 border-t border-divider bg-transparent px-2.5 py-1.5 text-ui-xs text-primary hover:bg-secondary",
          )}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? t("confirmCollapse") : t("confirmNoteExpand")}
        </button>
      ) : null}
    </div>
  );
}

function clip(segments: DiffSegment[], budget: number): DiffSegment[] {
  const out: DiffSegment[] = [];
  let left = budget;
  for (const one of segments) {
    if (left <= 0) break;
    out.push(one.text.length <= left ? one : { ...one, text: one.text.slice(0, left) });
    left -= one.text.length;
  }
  return out;
}
