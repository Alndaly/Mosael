import React from "react";
import { noteSnippet } from "@/features/notes/noteSnippet";
import {
  CheckSquare,
  Copy,
  FileOutput,
  FileText,
  Pencil,
  RotateCcw,
  Star,
  Trash2,
  X,
} from "lucide-react";
import type { Note } from "@/api/domains/notes";
import { Button } from "@/components/ui/button";
import {
  ContextMenu,
  ContextMenuTrigger,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
} from "@/components/ui/context-menu";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { IconButton } from "@/components/ui/icon-button";
import { MenuItemBody } from "@/components/ui/menu";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { ConfirmDialog } from "@/components/app/modals";
import { useNoteStrings } from "./strings";
import { isImeKeystroke } from "@/lib/shortcuts";
export type NoteListAction =
  | "favorite"
  | "unfavorite"
  | "trash"
  | "restore"
  | "delete"
  | "rename"
  | "duplicate"
  | "export";
export function rangeSelection(
  ids: string[],
  anchor: string | null,
  target: string,
) {
  const end = ids.indexOf(target),
    start = anchor ? ids.indexOf(anchor) : end;
  return ids.slice(
    Math.min(start < 0 ? end : start, end),
    Math.max(start < 0 ? end : start, end) + 1,
  );
}
export function NoteList({
  notes,
  currentId,
  selecting,
  onSelecting,
  onOpen,
  onAction,
  empty,
  more,
}: {
  notes: Note[];
  currentId: string | null;
  selecting: boolean;
  onSelecting: (v: boolean) => void;
  onOpen: (id: string) => void;
  onAction: (
    action: NoteListAction,
    notes: Note[],
    value?: string,
  ) => Promise<string[]>;
  empty: React.ReactNode;
  more?: React.ReactNode;
}) {
  const s = useNoteStrings();
  const [selected, setSelected] = React.useState<Set<string>>(new Set());
  const anchor = React.useRef<string | null>(null);
  const [context, setContext] = React.useState<string[]>([]);
  //: 在跑的是哪一样(收藏、导出、移到回收站……):转圈的是点的那一颗;别的动作和整列在这期间都点不了
  const [running, setRunning] = React.useState<NoteListAction | null>(null);
  const busy = running !== null;
  const [remove, setRemove] = React.useState<Note[]>([]);
  const [rename, setRename] = React.useState<Note | null>(null);
  const [title, setTitle] = React.useState("");
  const ids = notes.map((n) => n.id),
    visibleKey = ids.join(",");
  React.useEffect(() => {
    setSelected((old) => new Set([...old].filter((id) => ids.includes(id))));
  }, [visibleKey]);
  React.useEffect(() => {
    if (!selecting) {
      setSelected(new Set());
      anchor.current = null;
    }
  }, [selecting]);
  const chosen = notes.filter((n) => selected.has(n.id));
  const targets = notes.filter((n) => context.includes(n.id));
  const allFavorite = targets.length > 0 && targets.every((n) => n.favorite);
  function toggle(id: string, shift = false) {
    onSelecting(true);
    setSelected((old) => {
      if (shift)
        return new Set([...old, ...rangeSelection(ids, anchor.current, id)]);
      const next = new Set(old);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
    if (!shift) anchor.current = id;
  }
  function clear() {
    setSelected(new Set());
    anchor.current = null;
    onSelecting(false);
  }
  async function run(action: NoteListAction, rows: Note[], value?: string) {
    if (busy || !rows.length) return;
    setRunning(action);
    try {
      const done = await onAction(action, rows, value);
      if (["trash", "restore", "delete"].includes(action))
        setSelected(
          (old) => new Set([...old].filter((id) => !done.includes(id))),
        );
      if (action === "rename" && done.length) setRename(null);
      setRemove([]);
    } finally {
      setRunning(null);
    }
  }
  function contextAt(event: React.MouseEvent) {
    const row = (event.target as HTMLElement).closest<HTMLElement>(
      "[data-note-id]",
    );
    if (!row) {
      setContext([...selected]);
      return;
    }
    const id = row.dataset.noteId!;
    setContext(selected.has(id) ? [...selected] : [id]);
  }
  return (
    <>
      <ContextMenu>
        <ContextMenuTrigger asChild disabled={busy}>
          <div
            className={`notes-list ${!notes.length ? "notes-list-empty" : ""}`}
            role="group"
            aria-label={s.noteList}
            tabIndex={0}
            onContextMenuCapture={contextAt}
            onKeyDown={(e) => {
              if (isImeKeystroke(e)) return;
              if (
                (e.target as HTMLElement).closest(
                  'input:not([type="checkbox"]),textarea,[contenteditable="true"]',
                )
              )
                return;
              if (e.key === "Escape") {
                e.preventDefault();
                clear();
              }
              if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "a") {
                e.preventDefault();
                onSelecting(true);
                setSelected(new Set(ids));
              }
            }}
          >
            {notes.map((n) => (
              <div
                key={n.id}
                className="note-list-entry"
                data-note-id={n.id}
                data-selected={selected.has(n.id)}
              >
                {selecting && (
                  <input
                    type="checkbox"
                    className="note-list-check"
                    aria-label={`${s.selectNote} ${n.title || s.untitled}`}
                    checked={selected.has(n.id)}
                    disabled={busy}
                    onChange={() => toggle(n.id)}
                  />
                )}
                <button
                  className="note-list-row"
                  disabled={busy}
                  aria-current={currentId === n.id}
                  onClick={(e) => {
                    if (selecting || e.metaKey || e.ctrlKey || e.shiftKey)
                      toggle(n.id, e.shiftKey);
                    else {
                      clear();
                      anchor.current = n.id;
                      onOpen(n.id);
                    }
                  }}
                >
                  <strong>
                    {n.favorite && <Star size={12} fill="currentColor" />}
                    <Truncate>{n.title || s.untitled}</Truncate>
                  </strong>
                  <p>{noteSnippet(n.markdown, 100)}</p>
                  <time>
                    {new Date(n.updated_at).toLocaleDateString()}
                    {n.topics.length ? ` · ${n.topics.join(", ")}` : ""}
                  </time>
                </button>
              </div>
            ))}
            {!notes.length && empty}
            {more}
          </div>
        </ContextMenuTrigger>
        <ContextMenuContent onCloseAutoFocus={(e) => e.preventDefault()}>
          {targets.length === 1 && (
            <>
              <ContextMenuItem onSelect={() => onOpen(targets[0].id)}>
                <MenuItemBody icon={<FileText />} label={s.openNote} />
              </ContextMenuItem>
              {!targets[0].trashed && (
                <ContextMenuItem
                  onSelect={() => {
                    setRename(targets[0]);
                    setTitle(targets[0].title);
                  }}
                >
                  <MenuItemBody icon={<Pencil />} label={s.rename} />
                </ContextMenuItem>
              )}
              <ContextMenuItem onSelect={() => void run("duplicate", targets)}>
                <MenuItemBody icon={<Copy />} label={s.duplicate} />
              </ContextMenuItem>
              <ContextMenuSeparator />
            </>
          )}
          <ContextMenuItem
            disabled={!targets.length || busy}
            onSelect={() =>
              void run(allFavorite ? "unfavorite" : "favorite", targets)
            }
          >
            <MenuItemBody icon={<Star />} label={allFavorite ? s.unfavorite : s.favorite} />
          </ContextMenuItem>
          <ContextMenuItem
            disabled={!targets.length || busy}
            onSelect={() => void run("export", targets)}
          >
            <MenuItemBody icon={<FileOutput />} label={s.export} />
          </ContextMenuItem>
          <ContextMenuSeparator />
          <ContextMenuItem
            disabled={!targets.length || busy}
            onSelect={() =>
              void run(targets[0]?.trashed ? "restore" : "trash", targets)
            }
          >
            <MenuItemBody
              icon={targets[0]?.trashed ? <RotateCcw /> : <Trash2 />}
              label={targets[0]?.trashed ? s.restoreTrash : s.moveTrash}
            />
          </ContextMenuItem>
          {!!targets.length && targets.every((n) => n.trashed) && (
            <ContextMenuItem
              className="text-destructive"
              disabled={busy}
              onSelect={() => setRemove(targets)}
            >
              <MenuItemBody icon={<Trash2 />} label={s.deleteForever} />
            </ContextMenuItem>
          )}
          <ContextMenuSeparator />
          <ContextMenuItem
            disabled={!targets.length}
            onSelect={() => {
              onSelecting(true);
              setSelected(new Set(context));
            }}
          >
            <MenuItemBody icon={<CheckSquare />} label={s.selectNotes} />
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>
      {selecting && (
        <div className="note-selection-bar" aria-label={s.batchActions}>
          <div>
            <label>
              <input
                type="checkbox"
                checked={!!notes.length && selected.size === notes.length}
                disabled={busy}
                aria-label={s.selectVisible}
                onChange={(e) =>
                  setSelected(e.target.checked ? new Set(ids) : new Set())
                }
              />
              <span>{s.selectedCount(chosen.length)}</span>
            </label>
            <IconButton
              unstyled
              className="note-icon"
              label={s.cancelSelection}
              disabled={busy}
              onClick={clear}
            >
              <X size={15} />
            </IconButton>
          </div>
          <div>
            <IconButton
              label={
                chosen.length && chosen.every((n) => n.favorite)
                  ? s.unfavorite
                  : s.favorite
              }
              disabled={!chosen.length || busy}
              loading={running === "favorite" || running === "unfavorite"}
              disabledReason={!chosen.length && s.noneSelected}
              onClick={() =>
                void run(
                  chosen.every((n) => n.favorite) ? "unfavorite" : "favorite",
                  chosen,
                )
              }
            >
              <Star />
            </IconButton>
            <IconButton
              label={s.export}
              disabled={!chosen.length || busy}
              loading={running === "export"}
              disabledReason={!chosen.length && s.noneSelected}
              onClick={() => void run("export", chosen)}
            >
              <FileOutput />
            </IconButton>
            <Hint disabledReason={!chosen.length && s.noneSelected}>
              <Button
                variant="ghost"
                size="sm"
                disabled={!chosen.length || busy}
                loading={running === "trash" || running === "restore"}
                onClick={() =>
                  void run(chosen[0]?.trashed ? "restore" : "trash", chosen)
                }
              >
                {chosen[0]?.trashed ? <RotateCcw /> : <Trash2 />}
                {chosen[0]?.trashed ? s.restoreTrash : s.moveTrash}
              </Button>
            </Hint>
            {!!chosen.length && chosen.every((n) => n.trashed) && (
              <IconButton
                className="text-destructive"
                label={s.deleteForever}
                disabled={busy}
                onClick={() => setRemove(chosen)}
              >
                <Trash2 />
              </IconButton>
            )}
          </div>
        </div>
      )}
      <Dialog
        open={!!rename}
        onOpenChange={(open) => {
          if (!open && !busy) setRename(null);
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogTitle>{s.rename}</DialogTitle>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (rename) void run("rename", [rename], title);
            }}
          >
            <input
              className="note-rename-input"
              aria-label={s.title}
              autoFocus
              maxLength={240}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
            <div className="mt-4 flex justify-end">
              <Button type="submit" disabled={busy} loading={running === "rename"}>
                {s.apply}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={!!remove.length}
        title={`${s.deleteForever} · ${remove.length}`}
        body={s.deleteWarning}
        onCancel={() => {
          if (!busy) setRemove([]);
        }}
        pending={running === "delete"}
        onConfirm={() => void run("delete", remove)}
      />
    </>
  );
}
