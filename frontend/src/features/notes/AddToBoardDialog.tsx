import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LayoutGrid, Loader2, Plus, Search } from "lucide-react";
import { toast } from "sonner";

import { appendBoardNote, createBoard, listBoards, type BoardSummary } from "@/api/domains/boards";
import type { NoteSource } from "@/api/domains/notes";
import { errorText } from "@/api/errorMessage";
import { boardKeys } from "@/api/queryKeys";
import { usePreferences } from "@/app/preferences";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { Input } from "@/components/ui/input";
import { MenuItem } from "@/components/ui/menu";
import { openBoardItem } from "@/lib/deepLink";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { useNoteStrings } from "./strings";

/** 每个工作区上次「加到画板」加进去的那张,排在最前面。 */
const lastBoardKey = (workspaceId: string) => `mosael.notes.lastBoard.${workspaceId}`;
function lastBoard(workspaceId: string): string | null {
  try { return window.localStorage.getItem(lastBoardKey(workspaceId)); } catch { return null; }
}
function rememberBoard(workspaceId: string, boardId: string) {
  try { window.localStorage.setItem(lastBoardKey(workspaceId), boardId); } catch { /* 记不住只是少一个便利 */ }
}

/**
 * 「加到画板」的画板选择器:上次加过的那张排最前,其余按最近改过的排;能搜;找不到就新建一张(用搜索框里的字当名字)。
 *
 * 挑了就把选中的字作为一张便签追加上去 —— 服务端落在那张板当前的画布上、摆在空位(POST /boards/{id}/notes),
 * 记着来自哪篇笔记;加完一条提示,带「打开画板」(打开那张板并把视野挪到这一格)。
 */
export function AddToBoardDialog({ workspaceId, text, source, onClose }: {
  workspaceId: string;
  /** 要放上去的字(选区的纯文字:便签按纯文字显示)。 */
  text: string;
  /** 来自哪篇笔记(就是这一篇)。 */
  source?: NoteSource;
  onClose: () => void;
}) {
  const s = useNoteStrings();
  const sb = s.board;
  const { locale } = usePreferences();
  const qc = useQueryClient();
  const [q, setQ] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const boards = useQuery({ queryKey: boardKeys.list(workspaceId), queryFn: () => listBoards(workspaceId) });
  const recent = lastBoard(workspaceId);
  const ordered = React.useMemo(() => {
    const rank = (board: BoardSummary) => (board.id === recent ? 1 : 0);
    return [...(boards.data ?? [])].sort((a, b) => rank(b) - rank(a) || b.updated_at.localeCompare(a.updated_at));
  }, [boards.data, recent]);
  const term = q.trim().toLowerCase();
  const shown = term ? ordered.filter((board) => board.name.toLowerCase().includes(term)) : ordered;

  async function addTo(boardId: string, name: string) {
    setBusy(true);
    try {
      const added = await appendBoardNote(boardId, {
        workspace_id: workspaceId,
        text,
        ...(source ? { source_note: { note_id: source.id, revision: source.revision ?? 1, title: source.label } } : {}),
      });
      rememberBoard(workspaceId, boardId);
      void qc.invalidateQueries({ queryKey: boardKeys.everywhere() });
      toast.success(sb.added(name), { action: { label: sb.open, onClick: () => openBoardItem(added.board_id, added.item_id) } });
      onClose();
    } catch (error) {
      toast.error(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  async function addToNew() {
    setBusy(true);
    try {
      const name = q.trim() || sb.defaultName;
      const board = await createBoard({ workspace_id: workspaceId, name });
      await addTo(board.id, board.name || name);
    } catch (error) {
      toast.error(errorText(error));
      setBusy(false);
    }
  }

  return (
    <ModalShell
      open
      onOpenChange={(open) => { if (!open && !busy) onClose(); }}
      title={sb.title}
      className="w-[420px]"
      header={(
        <div className="relative">
          <Search size={16} aria-hidden className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input type="search" className="!pl-9" aria-label={sb.search} placeholder={sb.search} value={q} maxLength={120}
            disabled={busy} onChange={(event) => setQ(event.target.value)} />
        </div>
      )}
    >
      <div className={cn(DIALOG_FIELD, "gap-2")}>
        <div role="list" aria-busy={boards.isFetching} className="grid max-h-72 min-h-24 content-start overflow-y-auto overscroll-contain rounded-lg border border-field-border p-1">
          {boards.isPending ? (
            <p role="status" className="m-auto flex items-center gap-2 text-ui-sm text-muted-foreground">
              <Loader2 size={14} className="animate-mosael-spin motion-reduce:animate-none" aria-hidden />{sb.loading}
            </p>
          ) : boards.isError ? (
            <p role="alert" className="m-auto px-3 text-center text-ui-sm text-muted-foreground">{errorText(boards.error)}</p>
          ) : shown.length === 0 ? (
            <p className="m-auto px-3 text-center text-ui-sm text-muted-foreground">{term ? sb.noMatch : sb.empty}</p>
          ) : shown.map((board) => (
            <div role="listitem" key={board.id} className="min-w-0">
              {/* 挑选列表(role=list)里的一行,不是菜单:样子和菜单项同一套,角色仍是按钮。 */}
              <MenuItem role="button" data-board-row={board.id} disabled={busy}
                className="focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                onClick={() => void addTo(board.id, board.name)}
                icon={<LayoutGrid className="text-muted-foreground" />} label={board.name} truncate
                hint={relativeTime(board.updated_at, locale)} />
            </div>
          ))}
        </div>
        <MenuItem role="button" disabled={busy} className="text-primary" onClick={() => void addToNew()}
          icon={<Plus />} label={q.trim() ? sb.newBoardNamed(q.trim()) : sb.newBoard} truncate />
      </div>
    </ModalShell>
  );
}
