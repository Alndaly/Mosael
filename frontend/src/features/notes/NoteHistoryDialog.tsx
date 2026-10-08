import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { toast } from "sonner";

import { getNoteRevision, listNoteRevisions, type NoteRevisionSummary } from "@/api/domains/notes";
import { errorText } from "@/api/errorMessage";
import { noteKeys } from "@/api/queryKeys";
import { useAuth } from "@/app/auth";
import { useI18n, usePreferences } from "@/app/preferences";
import {
  AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { DiffSegments } from "@/components/app/DiffSegments";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { segmentedItemClass, segmentedListClass } from "@/components/ui/segmented";
import { IconButton } from "@/components/ui/icon-button";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { dayGroupOf, groupByLocalDay } from "@/lib/dayGroups";
import { diffText } from "@/lib/textDiff";
import { NoteReader } from "./NoteEditor";
import { useNoteStrings } from "./strings";
import { diffDocument, type DocumentDiffBlock } from "./versionDiff";
import { versionClock, versionMoment, versionSpan } from "./versionTime";

type Content = { revision: number; title: string; markdown: string };
/** 编辑器里的这一份:多带一个保存序号 —— 连续编辑改写的是同一版,版本号不变,列表要跟着它刷新。 */
type Current = Content & { saveSeq: number };
type View = "preview" | "current" | "previous";

/**
 * 笔记的版本记录。
 *
 * 一个大弹窗:左边是按天分组的版本列表(新的在上,顶上那一版标「当前版本」),右边是选中那一版的预览,正文按阅读宽度排。
 * 连续的手动编辑在存储上就合成了一版(domain/notes/history):列表上每一项写着它改了多少(+120 −30 字、改了标题),
 * 悬停时间看得到这一版从几点写到几点。
 * 当前版本就是编辑器里这一份(`current`),不再去读一遍;别的版本按需读,读过的留在缓存里。
 *
 * - 「恢复此版本」先确认:恢复会新建一个版本,现有版本都还在 —— 当前版本上没有这颗;
 * - 「复制这一版的内容」复制的是正文的 Markdown;
 * - 列表里上下键、Home / End 切换版本,焦点跟着走(只有选中那一项在 Tab 序列里);
 * - 右边切「预览 / 和当前版本对比 / 和上一版对比」。对比一律从旧到新画:划掉的是后来(或这一版)删掉的,高亮的是
 *   后来(或这一版)加上的。切到别的版本,看的方式不变;那一版用不了的方式(当前版本和当前比、第 1 版没有上一版)点不了。
 */
export function NoteHistoryDialog({ open, onOpenChange, workspaceId, noteId, current, focusRevision, onRestore }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string;
  noteId: string;
  /** 编辑器里的这一份 —— 列表顶上那一版。 */
  current: Current;
  /** 打开时选中哪一版(「查看引用版本」);不给就是当前版本。 */
  focusRevision: number | null;
  /** 恢复成新的一版;做完由笔记页关掉弹窗。 */
  onRestore: (revision: number) => Promise<void>;
}) {
  const s = useNoteStrings();
  const v = s.versions;
  const t = useI18n();
  const { locale } = usePreferences();
  const versions = useQuery({
    queryKey: noteKeys.history(noteId, current.saveSeq), queryFn: () => listNoteRevisions(workspaceId, noteId), enabled: open,
  });
  const [selected, setSelected] = React.useState<number | null>(null);
  //: 每次打开重新挑:引用的那一版,或者当前版本。开着的时候 current.revision 变了(恢复完)不重挑。
  React.useEffect(() => { if (open) setSelected(focusRevision ?? current.revision); }, [open, focusRevision]); // eslint-disable-line react-hooks/exhaustive-deps
  const items = versions.data ?? [];
  const chosen = selected ?? current.revision;
  const isCurrent = chosen === current.revision;
  const content = useQuery({
    queryKey: noteKeys.revisionContent(noteId, chosen), queryFn: () => getNoteRevision(workspaceId, noteId, chosen),
    enabled: open && !isCurrent, staleTime: Infinity,
  });
  const shown: Content | undefined = isCurrent ? current : content.data;
  const [view, setView] = React.useState<View>("preview");
  //: 「上一版」是列表上紧挨着的那一项(更早的一版)。列表还没回来时按版本号退一步。
  const at = items.findIndex((one) => one.revision === chosen);
  const previous = at >= 0 ? (items[at + 1]?.revision ?? 0) : chosen - 1;
  const usable: Record<View, boolean> = { preview: true, current: !isCurrent, previous: previous >= 1 };
  const showing: View = usable[view] ? view : "preview";
  const before = useQuery({
    queryKey: noteKeys.revisionContent(noteId, previous), queryFn: () => getNoteRevision(workspaceId, noteId, previous),
    enabled: open && showing === "previous", staleTime: Infinity,
  });
  const pair: [Content, Content] | null = !shown ? null
    : showing === "current" ? [shown, current]
    : showing === "previous" ? (before.data ? [before.data, shown] : null)
    : null;
  const chosenItem = at >= 0 ? items[at] : undefined;
  const only = items.length === 1;

  const rows = React.useRef(new Map<number, HTMLButtonElement>());
  const body = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => { if (body.current) body.current.scrollTop = 0; }, [chosen]);
  const order = items.map((one) => one.revision);
  const move = (event: React.KeyboardEvent, revision: number) => {
    const index = order.indexOf(revision);
    const next = { ArrowDown: index + 1, ArrowUp: index - 1, Home: 0, End: order.length - 1 }[event.key];
    if (next === undefined || next < 0 || next >= order.length) return;
    event.preventDefault();
    setSelected(order[next]);
    rows.current.get(order[next])?.focus();
  };

  const [confirming, setConfirming] = React.useState(false);
  const [restoring, setRestoring] = React.useState(false);
  const restore = async () => {
    setRestoring(true);
    try { await onRestore(chosen); setConfirming(false); } finally { setRestoring(false); }
  };
  const copy = () => {
    if (!shown) return;
    void navigator.clipboard?.writeText(shown.markdown).then(() => toast.success(v.copied(chosen)), (e) => toast.error(errorText(e)));
  };

  const now = new Date();
  const days = groupByLocalDay(items, (one) => one.created_at);
  const dayName = (key: string) => {
    const day = dayGroupOf(key, now, locale);
    return day.kind === "today" ? v.today : day.kind === "yesterday" ? v.yesterday : day.text;
  };
  const row = (item: NoteRevisionSummary) => {
    const active = item.revision === chosen;
    return (
      <li key={item.revision}>
        <button type="button" className="note-history-item" aria-current={active} tabIndex={active ? 0 : -1}
          ref={(node) => { if (node) rows.current.set(item.revision, node); else rows.current.delete(item.revision); }}
          onClick={() => setSelected(item.revision)} onKeyDown={(event) => move(event, item.revision)}>
          <span className="note-history-item-head">
            <Hint label={versionSpan(item.started_at, item.created_at, locale)} side="right">
              <time dateTime={item.created_at}>{versionClock(item.created_at, locale)}</time>
            </Hint>
            {item.revision === current.revision && <span className="note-history-badge">{v.current}</span>}
            <span className="note-history-number">{v.version(item.revision)}</span>
          </span>
          <span className="note-history-meta">
            <VersionHow item={item} className="note-history-how" />
            <VersionChange item={item} />
          </span>
        </button>
      </li>
    );
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="note-history h-[min(880px,calc(100dvh-2rem))] w-[min(1100px,calc(100vw-2rem))] grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] gap-0 overflow-hidden p-0">
          <header className="note-history-header">
            <DialogTitle>{s.history}</DialogTitle>
            <DialogDescription>{v.hint}</DialogDescription>
          </header>
          <div className="note-history-layout">
            <div className="note-history-list">
              <ul aria-label={v.list}>
                {days.map((day) => (
                  <li key={day.key} className="note-history-day">
                    <h3>{dayName(day.key)}</h3>
                    <ul>{day.items.map(row)}</ul>
                  </li>
                ))}
              </ul>
              {only && <p className="note-history-only">{v.onlyOne}</p>}
            </div>
            <section className="note-history-main" aria-label={s.versionContent}>
              <div className="note-history-bar">
                <div className="note-history-what">
                  <strong>{v.version(chosen)}</strong>
                  {chosenItem && <span>{versionMoment(chosenItem.created_at, locale, now, v)}</span>}
                  {chosenItem && <VersionHow item={chosenItem} />}
                  {isCurrent && <span className="note-history-badge">{v.current}</span>}
                </div>
                <div className="note-history-actions">
                  <IconButton label={v.copy} disabled={!shown} onClick={copy}>
                    <Copy size={16} strokeWidth={1.7} aria-hidden="true" />
                  </IconButton>
                  {!isCurrent && <Button size="sm" disabled={!shown} onClick={() => setConfirming(true)}>{v.restore}</Button>}
                </div>
              </div>
              <div className="note-history-views">
                <div role="radiogroup" aria-label={v.views} className={segmentedListClass("sm")}>
                  {(["preview", "current", "previous"] as const).map((one) => (
                    <button key={one} type="button" role="radio" aria-checked={showing === one} disabled={!usable[one]}
                      className={segmentedItemClass(showing === one, "sm")}
                      onClick={() => setView(one)}>
                      {{ preview: v.preview, current: v.compareCurrent, previous: v.comparePrevious }[one]}
                    </button>
                  ))}
                </div>
                {showing !== "preview" && <p className="note-history-legend">{showing === "current" ? v.legendCurrent : v.legendPrevious}</p>}
              </div>
              <div ref={body} className="note-history-body">
                <article className="note-history-paper">
                  {showing !== "preview" ? (
                    pair ? (
                      <VersionDiff key={`${showing}-${chosen}`} before={pair[0]} after={pair[1]} untitled={s.untitled}
                        empty={showing === "current" ? v.sameAsCurrent : v.sameAsPrevious} unfold={v.unfold} />
                    ) : (content.isError || before.isError) ? (
                      <p className="note-history-status">{v.loadFailed}</p>
                    ) : (
                      <p className="note-history-status">{s.loading}</p>
                    )
                  ) : shown ? (
                    <>
                      <h1 className="note-history-title">{shown.title || s.untitled}</h1>
                      <NoteReader markdown={shown.markdown} previewImages />
                    </>
                  ) : content.isError ? (
                    <p className="note-history-status">{v.loadFailed}</p>
                  ) : (
                    <p className="note-history-status">{s.loading}</p>
                  )}
                </article>
              </div>
            </section>
          </div>
        </DialogContent>
      </Dialog>
      <AlertDialog open={confirming} onOpenChange={(next) => { if (!next && !restoring) setConfirming(false); }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{v.restoreTitle(chosen)}</AlertDialogTitle>
            <AlertDialogDescription>{v.restoreBody(chosen, current.revision + 1)}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={restoring}>{t("cancel")}</AlertDialogCancel>
            <Button loading={restoring} onClick={() => void restore()}>{v.restoreConfirm}</Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

/**
 * 这一版怎么来的(手动编辑、智能体修改、从版本 N 恢复……),别人写的带上名字 —— 自己写的不念自己。
 * 单独一个组件:看「是不是自己」要读登录态,只在列表真的摆出来时才读。
 */
function VersionHow({ item, className }: { item: NoteRevisionSummary; className?: string }) {
  const v = useNoteStrings().versions;
  const viewer = useAuth().user?.id;
  const origin = item.origin === "restore" && item.restored_from ? v.restoredFrom(item.restored_from) : v.origins[item.origin];
  const by = item.created_by && item.created_by !== viewer && item.created_by_name ? item.created_by_name : "";
  return <Truncate className={className}>{by ? `${origin} · ${by}` : origin}</Truncate>;
}

/** 这一版改了多少:「+120 −30 字」「改了标题」。只改了来源的那种两样都没有,就不写。 */
function VersionChange({ item }: { item: NoteRevisionSummary }) {
  const v = useNoteStrings().versions;
  const words = item.chars_added > 0 || item.chars_removed > 0;
  if (!words && !item.title_changed) return null;
  return (
    <span className="note-history-change">
      {words && (
        <span>
          {item.chars_added > 0 && <span className="note-history-added">+{item.chars_added}</span>}
          {item.chars_removed > 0 && <span className="note-history-removed">−{item.chars_removed}</span>}
          {v.chars}
        </span>
      )}
      {item.title_changed && <span>{v.titleChanged}</span>}
    </span>
  );
}

/** 没改的行露出几行上下文;再多就折起来。 */
const CONTEXT_LINES = 2;
/** 折起来至少藏这么多行 —— 只藏一两行的话,那颗「展开」比它藏的字还占地方。 */
const MIN_FOLD = 3;

/** 两版的对比:标题改了就画标题的差异;正文按行对齐,改了的那几行按字画,大段没改的折起来。 */
function VersionDiff({ before, after, empty, untitled, unfold }: {
  before: Content; after: Content; empty: string; untitled: string; unfold: (lines: number) => string;
}) {
  const blocks = React.useMemo(() => diffDocument(before.markdown, after.markdown), [before.markdown, after.markdown]);
  const title = before.title === after.title ? null : diffText(before.title, after.title);
  const [opened, setOpened] = React.useState<ReadonlySet<number>>(new Set());
  if (!title && !blocks.some((block) => block.kind === "change")) return <p className="note-history-status">{empty}</p>;
  const same = (block: Extract<DocumentDiffBlock, { kind: "same" }>, index: number) => {
    const head = index === 0 ? 0 : CONTEXT_LINES;
    const tail = index === blocks.length - 1 ? 0 : CONTEXT_LINES;
    const hidden = block.lines.length - head - tail;
    const line = (text: string, at: number) => <div key={at} className="note-diff-line">{text || "\u00a0"}</div>;
    if (hidden < MIN_FOLD || opened.has(index)) return <div key={index}>{block.lines.map(line)}</div>;
    return (
      <div key={index}>
        {block.lines.slice(0, head).map(line)}
        <button type="button" className="note-diff-fold" onClick={() => setOpened(new Set([...opened, index]))}>{unfold(hidden)}</button>
        {block.lines.slice(block.lines.length - tail).map((text, at) => line(text, block.lines.length - tail + at))}
      </div>
    );
  };
  return (
    <div className="note-diff">
      <h1 className="note-history-title">{title ? <DiffSegments segments={title} /> : after.title || untitled}</h1>
      {blocks.map((block, index) => block.kind === "change"
        ? <p key={index} className="note-diff-change"><DiffSegments segments={block.segments} /></p>
        : same(block, index))}
    </div>
  );
}
