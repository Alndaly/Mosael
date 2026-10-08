import React from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookPlus, CornerDownLeft, FileText, Loader2, Search } from "lucide-react";
import { toast } from "sonner";
import { appendNote, createNote, listNotes, type Note, type NoteSource } from "@/api/domains/notes";
import { noteKeys } from "@/api/queryKeys";
import { errorText } from "@/api/errorMessage";
import { usePreferences } from "@/app/preferences";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { MenuItem } from "@/components/ui/menu";
import { Hint } from "@/components/ui/tooltip";
import { segmentedItemClass, segmentedListClass } from "@/components/ui/segmented";
import { relativeTime } from "@/lib/time";
import { useNoteStrings } from "./strings";

/** 一种可选的正文形状。给了两份以上,对话框就多一排切换;只给正文的调用方什么都不用改。 */
export type SaveToNoteVariant = { id: string; label: string; markdown: string; sources: NoteSource[] };

/** 正在存的是「新建一篇」(笔记 id 不会长这样)。 */
const NEW_NOTE = "__new__";

/**
 * 「保存到笔记」对话框。逐字稿、字幕、对话气泡、画板节点共用这一个。
 *
 * 版面是**先定写什么,再定写到哪**:正文形状(有两份以上时)+ 一句"将写入多少",然后是两个
 * 并列的去处 —— 新建一篇、追加到已有的一篇。此前两个去处挤在一起:标题框和「新建笔记」一行,
 * 紧跟着一行灰字和一串没有边界的标题,读不出哪几样是一组、哪一行能点,列表还一路顶到弹窗底边。
 */
export function SaveToNote({workspaceId, content, sources = [], variants, className, label, onSaved, trigger}: {
  workspaceId: string; content?: string; sources?: NoteSource[]; variants?: SaveToNoteVariant[];
  className?: string; label?: string; onSaved?: (note: Note) => void;
  /** 入口长什么样由宿主定(画板操作条上是一枚图标,和别的动作同一种);不给就是默认那颗文字按钮。 */
  trigger?: (props: {open: () => void; disabled: boolean; label: string}) => React.ReactNode;
}) {
  const s = useNoteStrings(); const qc = useQueryClient(); const { locale } = usePreferences();
  const [open, setOpen] = React.useState(false); const [title, setTitle] = React.useState(""); const [q, setQ] = React.useState("");
  //: 正在存到哪:新建(`NEW_NOTE`)还是追加到哪一篇(它的 id)。转圈的是那一处,别的在这期间都点不了
  const [savingTo, setSavingTo] = React.useState<string | null>(null); const busy = savingTo !== null;
  const [variantId, setVariantId] = React.useState(variants?.[0]?.id ?? "");
  // 打字过程中沿用上一份结果,不让列表在每个字之间塌成"载入中"再弹回来。
  const notes = useQuery({queryKey: noteKeys.search(workspaceId, q), queryFn: () => listNotes(workspaceId, q), enabled: open, placeholderData: keepPreviousData});
  const listRef = React.useRef<HTMLDivElement | null>(null);
  const ids = React.useId();
  // 选中的那一份没了(调用方换了可选项)就退回第一份,不要停在一个不存在的 id 上。
  const chosen = variants?.find(v => v.id === variantId) ?? variants?.[0];
  const markdown = chosen ? chosen.markdown : (content ?? "");
  const chosenSources = chosen ? chosen.sources : sources;
  const candidates = notes.data?.filter(n => !n.trashed) ?? [];
  async function save(target?: Note) { setSavingTo(target?.id ?? NEW_NOTE); try {
    const n = target ? await appendNote(target, markdown, chosenSources) : await createNote(workspaceId, {title: title.trim() || markdown.replace(/[#*>\n]/g, " ").slice(0, 60), markdown, sources: chosenSources});
    void qc.invalidateQueries({queryKey: noteKeys.lists(workspaceId)}); void qc.invalidateQueries({queryKey: noteKeys.detail(workspaceId, n.id)});
    toast.success(s.done); onSaved?.(n); setOpen(false);
  } catch (e) { toast.error(errorText(e)); } finally { setSavingTo(null); } }

  // 列表的键盘走法:上下键在行之间挪、Home/End 到两端,从搜索框按 ↓ 进列表、在第一行按 ↑ 回搜索框。
  // 每一行是一个普通按钮(Tab 也能走到),Enter / 空格就是追加 —— 不另造一套"高亮项"状态。
  const rows = () => [...(listRef.current?.querySelectorAll<HTMLButtonElement>("button[data-note-row]") ?? [])];
  function moveFocus(event: React.KeyboardEvent, from: number) {
    const all = rows(); if (!all.length) return;
    const to = event.key === "ArrowDown" ? from + 1 : event.key === "ArrowUp" ? from - 1 : event.key === "Home" ? 0 : event.key === "End" ? all.length - 1 : null;
    if (to === null) return;
    event.preventDefault();
    if (to < 0) { document.getElementById(`${ids}-search`)?.focus(); return; }
    all[Math.min(to, all.length - 1)]?.focus();
  }

  const triggerProps = {open: () => setOpen(true), disabled: !markdown.trim(), label: label || s.saveTo};
  return <>{trigger ? trigger(triggerProps) : <Hint disabledReason={triggerProps.disabled && s.nothingToSave}><button type="button" className={className || "inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-secondary"} disabled={triggerProps.disabled} onClick={triggerProps.open}><BookPlus size={13} />{triggerProps.label}</button></Hint>}
    <ModalShell open={open} onOpenChange={value => { if (!busy) setOpen(value); }} title={label || s.saveTo} className="w-[480px]">
      <div className="grid gap-6">
        {variants && <div className={DIALOG_FIELD}>
          {variants.length > 1 && <>
            <span id={`${ids}-shape`}>{s.shape}</span>
            {/* 两种形状等分整行 —— 和降噪强度那排是同一个分段控件,挤在左边的话读起来像两个标签页。 */}
            <div className={segmentedListClass("md", { fill: true })} role="radiogroup" aria-labelledby={`${ids}-shape`}>{variants.map(variant =>
              <button key={variant.id} type="button" role="radio" aria-checked={variant.id === chosen?.id} disabled={busy}
                className={segmentedItemClass(variant.id === chosen?.id)} onClick={() => setVariantId(variant.id)}>{variant.label}</button>)}</div>
          </>}
          <small data-slot="save-summary">{s.willSave(markdown.length, chosenSources.length)}</small>
        </div>}

        <section className={DIALOG_FIELD} aria-labelledby={`${ids}-new`}>
          <span id={`${ids}-new`}>{s.saveAsNew}</span>
          {/* 标题框和它的动作同一行、同一高度(40px);回车等于点「新建」。 */}
          <form className="flex gap-2" onSubmit={e => { e.preventDefault(); if (!busy) void save(); }}>
            <Input aria-label={s.noteTitle} value={title} onChange={e => setTitle(e.target.value)} placeholder={s.untitled} maxLength={240} disabled={busy} />
            <Button type="submit" className="shrink-0" disabled={busy} loading={savingTo === NEW_NOTE}>{s.create}</Button>
          </form>
          <small>{s.titleHint}</small>
        </section>

        <section className={DIALOG_FIELD} aria-labelledby={`${ids}-append`}>
          <span id={`${ids}-append`}>{s.append}</span>
          <div className="relative">
            {/* `!pl-9`:DIALOG_FIELD 给字段里的输入框统一上了 px-3(选择器更具体),搜索框要给左边的放大镜让位。 */}
            <Search size={16} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input id={`${ids}-search`} type="search" className="!pl-9" aria-label={s.search} value={q} onChange={e => setQ(e.target.value)} placeholder={s.search} maxLength={300}
              onKeyDown={e => { if (e.key === "ArrowDown") { e.preventDefault(); rows()[0]?.focus(); } }} />
          </div>
          {/* 列表有边界、有上限高度,自己滚 —— 不再一路顶到弹窗底边。 */}
          <div ref={listRef} role="list" aria-labelledby={`${ids}-append`} aria-busy={notes.isFetching}
            className="grid max-h-60 min-h-24 content-start overflow-y-auto overscroll-contain rounded-lg border border-field-border p-1">
            {notes.isPending ? <p role="status" className="m-auto flex items-center gap-2 text-ui-sm text-muted-foreground"><Loader2 size={14} className="animate-mosael-spin motion-reduce:animate-none" aria-hidden />{s.loading}</p>
              : notes.isError ? <p role="alert" className="m-auto px-3 text-center text-ui-sm text-muted-foreground">{errorText(notes.error)}</p>
              : !candidates.length ? <p className="m-auto px-3 text-center text-ui-sm text-muted-foreground">{q.trim() ? s.noResults : s.listEmpty}</p>
              : candidates.map((n, index) => <div role="listitem" key={n.id} className="min-w-0">
                {/* 挑选列表(role=list)里的一行,不是菜单:样子和菜单项同一套,角色仍是按钮。 */}
                <MenuItem role="button" data-note-row="" disabled={busy} aria-busy={savingTo === n.id || undefined}
                  className="group/row focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                  onKeyDown={e => moveFocus(e, index)} onClick={() => void save(n)}
                  icon={savingTo === n.id ? <Loader2 className="animate-mosael-spin" /> : <FileText className="text-muted-foreground" />}
                  label={n.title || s.untitled} truncate
                  //: 静止时是更新时间;悬停 / 聚焦时换成回车符号,说明"点它就是追加到这里"。
                  hint={<>
                    <span className="group-hover/row:hidden group-focus-visible/row:hidden">{relativeTime(n.updated_at, locale)}</span>
                    <CornerDownLeft aria-hidden className="hidden group-hover/row:block group-focus-visible/row:block" />
                  </>} />
              </div>)}
          </div>
        </section>
      </div>
    </ModalShell>
  </>;
}
