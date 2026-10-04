import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { toast } from "sonner";

import { getNoteRevision, listNoteRevisions, type NoteRevisionSummary } from "@/api/domains/notes";
import { errorText } from "@/api/errorMessage";
import { noteKeys } from "@/api/queryKeys";
import { useI18n, usePreferences } from "@/app/preferences";
import {
  AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Hint } from "@/components/ui/tooltip";
import { dayGroupOf, groupByLocalDay } from "@/lib/dayGroups";
import { NoteReader } from "./NoteEditor";
import { useNoteStrings } from "./strings";
import { versionClock, versionFullTime, versionMoment } from "./versionTime";

type Content = { revision: number; title: string; markdown: string };

/**
 * 笔记的版本记录。
 *
 * 一个大弹窗:左边是按天分组的版本列表(新的在上,顶上那一版标「当前版本」),右边是选中那一版的预览,正文按阅读宽度排。
 * 当前版本就是编辑器里这一份(`current`),不再去读一遍;别的版本按需读,读过的留在缓存里。
 *
 * - 「恢复此版本」先确认:恢复会新建一个版本,现有版本都还在 —— 当前版本上没有这颗;
 * - 「复制这一版的内容」复制的是正文的 Markdown;
 * - 列表里上下键、Home / End 切换版本,焦点跟着走(只有选中那一项在 Tab 序列里)。
 */
export function NoteHistoryDialog({ open, onOpenChange, workspaceId, noteId, current, focusRevision, onRestore }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaceId: string;
  noteId: string;
  /** 编辑器里的这一份 —— 列表顶上那一版。 */
  current: Content;
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
    queryKey: noteKeys.history(noteId, current.revision), queryFn: () => listNoteRevisions(workspaceId, noteId), enabled: open,
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
  const chosenItem = items.find((one) => one.revision === chosen);
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
            <Hint label={versionFullTime(item.created_at, locale)} side="right">
              <time dateTime={item.created_at}>{versionClock(item.created_at, locale)}</time>
            </Hint>
            {item.revision === current.revision && <span className="note-history-badge">{v.current}</span>}
            <span className="note-history-number">{v.version(item.revision)}</span>
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
                  {isCurrent && <span className="note-history-badge">{v.current}</span>}
                </div>
                <div className="note-history-actions">
                  <Hint label={v.copy}>
                    <button type="button" className="note-icon" aria-label={v.copy} disabled={!shown} onClick={copy}>
                      <Copy size={16} strokeWidth={1.7} aria-hidden="true" />
                    </button>
                  </Hint>
                  {!isCurrent && <Button size="sm" disabled={!shown} onClick={() => setConfirming(true)}>{v.restore}</Button>}
                </div>
              </div>
              <div ref={body} className="note-history-body">
                <article className="note-history-paper">
                  {shown ? (
                    <>
                      <h1 className="note-history-title">{shown.title || s.untitled}</h1>
                      <NoteReader markdown={shown.markdown} />
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
