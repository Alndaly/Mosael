import React from "react";
import { useStore } from "@xyflow/react";
import type { LucideIcon } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { isImeKeystroke } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";

/** 一格的名字最长多少字。**和后端 canvas.MAX_TITLE_CHARS 是同一个数**(contracts/shared-constants.json):
 *  这边放得进、那边存不下的话,整张画板的自动保存都会被拒 —— 用户只看到「画板没能保存」。 */
export const BOARD_ITEM_TITLE_MAX = 120;

/** 名字是一行字:空白(连同换行)收成单个空格、首尾去掉。和后端 _normalize_title 同一个口径 ——
 *  两边不一致的话,本地这份和存回来那份永远差一点。 */
export function cleanTitle(value: string): string {
  return value.split(/\s+/).filter(Boolean).join(" ");
}

/**
 * 节点上方那一行:种类图标 + **名字**(没起名就是种类名)。双击就地改名。
 *
 * 每一种节点都用这一个 —— 分组框的名字此前是它自己一枚输入框、别的节点只能显示种类名,
 * 于是一张板上摆着五个「图片」,人和智能体都分不清谁是谁。
 *
 * 是不是在改名由画布说了算(`renaming`):操作条上的「重命名」和双击名字进的是同一个状态,
 * 改完只落一次 —— 撤销一步回到改之前,而不是一个字一个字地退。
 */
export function BoardNodeLabel({
  icon: Icon,
  title,
  fallback,
  renaming,
  readOnly = false,
  onRenaming,
  onRename,
  className,
}: {
  icon: LucideIcon;
  title?: string;
  /** 没起名时显示什么(种类名)。也是输入框的占位 —— 清空名字就回到它。 */
  fallback: string;
  renaming: boolean;
  /** 评论/标记模式:只看,不改。 */
  readOnly?: boolean;
  onRenaming?: (renaming: boolean) => void;
  /** 改好的名字(已收拾过);空串 = 不要名字了。和原来一样就不调。 */
  onRename?: (title: string) => void;
  className?: string;
}) {
  const t = useI18n();
  //: **反着视口缩放** —— 标签跟着画布缩的话,它在屏幕上的高度一直在变,而上方那块操作条
  //: 的间距是按屏幕像素算的(NodeToolbar 的 offset)。两者对不上的结果:拉远时标签越缩越小,
  //: 操作条和节点之间的空当越拉越大,而下方的面板纹丝不动。
  const zoom = useStore((state) => state.transform[2]) || 1;
  const name = title?.trim() ?? "";
  const editable = !readOnly && Boolean(onRenaming && onRename);
  const editing = editable && renaming;

  return (
    <span
      data-board-node-label=""
      className={cn(
        "absolute bottom-full left-0 inline-flex max-w-60 origin-bottom-left items-center gap-1 pb-1 text-ui-2xs text-muted-foreground",
        //: 能改名的时候名字要接得住双击;不能改的时候让点击穿过去,和此前一样。
        editable ? "pointer-events-auto" : "pointer-events-none",
        className,
      )}
      style={{ transform: `scale(${1 / zoom})` }}
    >
      <Icon size={11} className="shrink-0" />
      {editing ? (
        <TitleEditor
          initial={name}
          placeholder={fallback}
          onCancel={() => onRenaming?.(false)}
          onCommit={(draft) => {
            onRenaming?.(false);
            const next = cleanTitle(draft);
            if (next !== name) onRename?.(next);
          }}
        />
      ) : (
        <span
          className={cn("min-w-0 truncate", editable && "cursor-text")}
          title={editable ? `${name || fallback} · ${t("boardRenameHint")}` : name || undefined}
          onDoubleClick={
            editable
              ? (event) => {
                  //: 不冒泡:便签的双击是「写正文」,画布空白处的双击是「加一张便签」。
                  event.stopPropagation();
                  onRenaming?.(true);
                }
              : undefined
          }
        >
          {name || fallback}
        </span>
      )}
    </span>
  );
}

/**
 * 就地改名的那一枚输入框。
 *
 * **草稿是它自己的**:打开时从名字抄一份,之后外面怎么重绘都不回灌 —— 自动保存、别处的改动
 * 让节点重绘时,正在打的字不会被旧名字盖回去。Enter / 失焦落下,Esc 放弃。
 *
 * **输入法选词时的 Enter / Esc 不算数**(`isComposing`,Safari 在 compositionend 之后那一下
 * 只给 keyCode 229):中文拼音打到一半按 Enter 是在上屏,不是在确认名字;按 Esc 是在撤掉候选词,
 * 不是在放弃改名。
 */
function TitleEditor({
  initial,
  placeholder,
  onCommit,
  onCancel,
}: {
  initial: string;
  placeholder: string;
  onCommit: (draft: string) => void;
  onCancel: () => void;
}) {
  const t = useI18n();
  const [draft, setDraft] = React.useState(initial);
  const input = React.useRef<HTMLInputElement | null>(null);
  //: 只结束一次:Enter 落下之后输入框被卸掉,浏览器还可能补一个 blur。
  const settled = React.useRef(false);
  const finish = (commit: boolean) => {
    if (settled.current) return;
    settled.current = true;
    if (commit) onCommit(draft);
    else onCancel();
  };

  React.useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);

  return (
    <input
      ref={input}
      aria-label={t("rename")}
      // nodrag/nopan:在框里选字不能变成拖节点、拖画布。
      className="nodrag nopan nowheel w-40 min-w-0 border-0 border-b border-primary bg-transparent p-0 text-ui-2xs text-foreground outline-none placeholder:text-muted-foreground"
      value={draft}
      maxLength={BOARD_ITEM_TITLE_MAX}
      placeholder={placeholder}
      onChange={(event) => setDraft(event.target.value)}
      onKeyDown={(event) => {
        //: 按键到此为止 —— 画布在 window 上听着 Esc(收起剪辑面板)和撤销,改名时的按键不是给它们的。
        event.stopPropagation();
        if (isImeKeystroke(event.nativeEvent)) return;
        if (event.key === "Enter") {
          event.preventDefault();
          finish(true);
        } else if (event.key === "Escape") {
          event.preventDefault();
          finish(false);
        }
      }}
      onBlur={() => finish(true)}
      onDoubleClick={(event) => event.stopPropagation()}
    />
  );
}
