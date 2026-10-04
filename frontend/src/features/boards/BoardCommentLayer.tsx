/**
 * 画板画布上的评论:评论模式下点哪儿落一条草稿(useBoardCommentDraft),和画在视口里的评论钉、
 * 草稿编辑框(BoardCommentLayer)。从 BoardCanvas 拆出来 —— 拖钉子、拖草稿的那几份临时状态只在这里用。
 */
import React from "react";
import { ViewportPortal, type ReactFlowInstance } from "@xyflow/react";
import { MessageSquare } from "lucide-react";

import type { CollaborationComment, WorkspaceMember } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { IconButton } from "@/components/ui/icon-button";
import { Hint } from "@/components/ui/tooltip";
import { CommentCard } from "@/features/collaboration/CommentCard";
import { CommentComposer, type CommentDraft } from "@/features/collaboration/CommentComposer";
import {
  canMoveComment,
  moveCommentAnchorByScreenDelta,
  shouldDismissCommentOverlay,
  shouldSuppressCommentPlacement,
  type CanvasCommentAnchor,
  type ScreenPoint,
} from "@/features/boards/boardCanvasModel";
import { cn } from "@/lib/utils";

/**
 * 评论草稿落在哪,以及画布外壳上判「这一下是不是在落草稿」的那几个捕获阶段的指针回调。
 * `paneHandlers` 原样挂到画布最外层那个 div 上;`suppressPaneClick` 给画布的点击判据用。
 */
export function useBoardCommentDraft({
  commentMode,
  activeCommentId,
  onSelectComment,
}: {
  commentMode: boolean;
  activeCommentId?: string | null;
  onSelectComment?: (comment: CollaborationComment | null) => void;
}) {
  const [draftAnchor, setDraftAnchor] = React.useState<NonNullable<CollaborationComment["anchor"]> | null>(null);
  const paneGesture = React.useRef<{
    x: number;
    y: number;
    moved: boolean;
    dismissedActive: boolean;
    startedInsideOverlay: boolean;
  } | null>(null);
  const suppressPaneClick = React.useRef(false);

  React.useEffect(() => {
    if (!shouldDismissCommentOverlay(Boolean(activeCommentId), Boolean(draftAnchor), false)) return;
    const dismissOnOutsidePointer = (event: PointerEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      const insideOverlay = Boolean(target?.closest("[data-board-comment-overlay], [data-suggestion-menu]"));
      if (!shouldDismissCommentOverlay(Boolean(activeCommentId), Boolean(draftAnchor), insideOverlay)) return;
      if (activeCommentId) onSelectComment?.(null);
      if (draftAnchor) setDraftAnchor(null);
    };
    document.addEventListener("pointerdown", dismissOnOutsidePointer, true);
    return () => document.removeEventListener("pointerdown", dismissOnOutsidePointer, true);
  }, [activeCommentId, draftAnchor, onSelectComment]);

  const paneHandlers = {
    onPointerDownCapture: (event: React.PointerEvent<HTMLDivElement>) => {
      if (!commentMode || event.button !== 0) return;
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest("[data-suggestion-menu], [data-board-comment-mode-hint]")) return;
      const startedInsideOverlay = Boolean(target?.closest("[data-board-comment-overlay]"));
      const dismissedActive = Boolean(activeCommentId || draftAnchor);
      paneGesture.current = {
        x: event.clientX,
        y: event.clientY,
        moved: false,
        dismissedActive: startedInsideOverlay ? false : dismissedActive,
        startedInsideOverlay,
      };
      if (startedInsideOverlay) return;
      if (activeCommentId) onSelectComment?.(null);
      if (draftAnchor) setDraftAnchor(null);
    },
    onPointerMoveCapture: (event: React.PointerEvent<HTMLDivElement>) => {
      const gesture = paneGesture.current;
      if (!gesture) return;
      if (Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) > 5) gesture.moved = true;
    },
    onPointerUpCapture: (event: React.PointerEvent<HTMLDivElement>) => {
      const gesture = paneGesture.current;
      paneGesture.current = null;
      if (!gesture) return;
      const target = event.target instanceof Element ? event.target : null;
      const endedInsideOverlay = Boolean(target?.closest("[data-board-comment-overlay], [data-suggestion-menu]"));
      if (!shouldSuppressCommentPlacement({ ...gesture, endedInsideOverlay })) return;
      // pointerup is followed by click. Keep the guard through that click, then release it.
      suppressPaneClick.current = true;
      window.setTimeout(() => { suppressPaneClick.current = false; }, 0);
    },
    onPointerCancelCapture: () => {
      paneGesture.current = null;
    },
  };

  return { draftAnchor, setDraftAnchor, suppressPaneClick, paneHandlers };
}

/** 评论钉和草稿编辑框。`visible` 关着时不画,但拖到一半的位置等临时状态留着(和拆出来之前一样)。 */
export function BoardCommentLayer({
  visible,
  rf,
  commentMode,
  comments,
  members,
  currentUserId,
  activeCommentId,
  draftAnchor,
  setDraftAnchor,
  onSelectComment,
  onCreateComment,
  onMoveComment,
  onDeleteComment,
}: {
  visible: boolean;
  rf: React.RefObject<ReactFlowInstance | null>;
  commentMode: boolean;
  comments: CollaborationComment[];
  members: WorkspaceMember[];
  currentUserId?: string | null;
  activeCommentId?: string | null;
  draftAnchor: CanvasCommentAnchor | null;
  setDraftAnchor: React.Dispatch<React.SetStateAction<CanvasCommentAnchor | null>>;
  onSelectComment?: (comment: CollaborationComment | null) => void;
  onCreateComment?: (anchor: CanvasCommentAnchor, draft: CommentDraft) => Promise<unknown>;
  onMoveComment?: (comment: CollaborationComment, anchor: CanvasCommentAnchor) => Promise<unknown>;
  onDeleteComment?: (comment: CollaborationComment) => Promise<unknown>;
}) {
  const t = useI18n();
  const [commentPositions, setCommentPositions] = React.useState<Record<string, { x: number; y: number }>>({});
  const commentDrag = React.useRef<{
    id: string;
    pointerId: number;
    startScreen: { x: number; y: number };
    origin: { x: number; y: number };
    nodeId?: string;
    moved: boolean;
    last?: { x: number; y: number };
  } | null>(null);
  const draftCommentDrag = React.useRef<{
    pointerId: number;
    startScreen: ScreenPoint;
    origin: CanvasCommentAnchor;
    moved: boolean;
  } | null>(null);
  const suppressCommentClick = React.useRef<string | null>(null);

  if (!visible) return null;
  return (
    <ViewportPortal>
      {comments.map((comment, index) => {
        const preview = commentPositions[comment.id];
        const x = preview?.x ?? comment.anchor?.x;
        const y = preview?.y ?? comment.anchor?.y;
        if (typeof x !== "number" || typeof y !== "number") return null;
        const active = commentMode && activeCommentId === comment.id;
        const movable = commentMode && Boolean(onMoveComment) && canMoveComment(comment.author_id, currentUserId);
        return (
          <div
            key={comment.id}
            data-board-comment-overlay=""
            className="nodrag nopan pointer-events-none absolute z-10 flex items-start gap-2"
            style={{ left: x, top: y }}
            onPointerDown={(event) => event.stopPropagation()}
            onMouseDown={(event) => event.stopPropagation()}
            onClick={(event) => event.stopPropagation()}
            onDoubleClick={(event) => event.stopPropagation()}
          >
            {/* 圆点上只有序号,这条评论说了什么悬停时看。 */}
            <Hint label={comment.body}>
            <button
              type="button"
              className={cn(
                "grid h-7 w-7 touch-none -translate-x-1/2 -translate-y-1/2 shrink-0 place-items-center rounded-full border text-ui-2xs font-semibold shadow-[var(--shadow-panel)] transition-transform hover:scale-110",
                movable && "cursor-grab active:cursor-grabbing",
                active
                  ? "border-primary bg-action text-action-foreground"
                  : "border-floating-border bg-panel/90 text-foreground backdrop-blur-xl",
              )}
              tabIndex={commentMode ? 0 : -1}
              style={{ pointerEvents: commentMode ? "auto" : "none" }}
              aria-label={`${t("comments")} ${index + 1}`}
              onPointerDown={(event) => {
                event.stopPropagation();
                if (!movable || event.button !== 0) return;
                event.currentTarget.setPointerCapture(event.pointerId);
                commentDrag.current = {
                  id: comment.id,
                  pointerId: event.pointerId,
                  startScreen: { x: event.clientX, y: event.clientY },
                  origin: { x, y },
                  nodeId: comment.anchor?.node_id ?? undefined,
                  moved: false,
                };
              }}
              onPointerMove={(event) => {
                const drag = commentDrag.current;
                const instance = rf.current;
                if (!drag || drag.id !== comment.id || drag.pointerId !== event.pointerId || !instance) return;
                if (!drag.moved && Math.hypot(event.clientX - drag.startScreen.x, event.clientY - drag.startScreen.y) <= 4) return;
                drag.moved = true;
                const start = instance.screenToFlowPosition(drag.startScreen);
                const current = instance.screenToFlowPosition({ x: event.clientX, y: event.clientY });
                drag.last = {
                  x: drag.origin.x + current.x - start.x,
                  y: drag.origin.y + current.y - start.y,
                };
                const next = drag.last;
                setCommentPositions((positions) => ({ ...positions, [comment.id]: next }));
              }}
              onPointerUp={(event) => {
                const drag = commentDrag.current;
                if (!drag || drag.id !== comment.id || drag.pointerId !== event.pointerId) return;
                commentDrag.current = null;
                if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
                if (!drag.moved || !drag.last) return;
                suppressCommentClick.current = comment.id;
                window.setTimeout(() => {
                  if (suppressCommentClick.current === comment.id) suppressCommentClick.current = null;
                }, 0);
                const anchor = { kind: "canvas" as const, ...drag.last, ...(drag.nodeId ? { node_id: drag.nodeId } : {}) };
                void Promise.resolve(onMoveComment?.(comment, anchor))
                  .catch(() => undefined)
                  .finally(() => {
                    setCommentPositions((positions) => {
                      const next = { ...positions };
                      delete next[comment.id];
                      return next;
                    });
                  });
              }}
              onPointerCancel={(event) => {
                const drag = commentDrag.current;
                if (!drag || drag.id !== comment.id || drag.pointerId !== event.pointerId) return;
                commentDrag.current = null;
                setCommentPositions((positions) => {
                  const next = { ...positions };
                  delete next[comment.id];
                  return next;
                });
              }}
              onClick={() => {
                if (suppressCommentClick.current === comment.id) {
                  suppressCommentClick.current = null;
                  return;
                }
                onSelectComment?.(comment);
              }}
            >
              {index + 1}
            </button>
            </Hint>
            {active && (
              <div className="-ml-3.5 -translate-y-3">
                <CommentCard comment={comment} members={members} currentUserId={currentUserId}
                  onDelete={onDeleteComment ? () => onDeleteComment(comment) : undefined} />
              </div>
            )}
          </div>
        );
      })}
      {draftAnchor && typeof draftAnchor.x === "number" && typeof draftAnchor.y === "number" && (
        <div
          data-board-comment-overlay=""
          className="nodrag nopan pointer-events-none absolute z-20 flex items-start gap-2"
          style={{ left: draftAnchor.x, top: draftAnchor.y }}
          onPointerDown={(event) => event.stopPropagation()}
          onMouseDown={(event) => event.stopPropagation()}
          onClick={(event) => event.stopPropagation()}
          onDoubleClick={(event) => event.stopPropagation()}
        >
          <IconButton
            unstyled
            type="button"
            data-comment-drag-handle=""
            className="pointer-events-auto grid h-7 w-7 touch-none -translate-x-1/2 -translate-y-1/2 shrink-0 cursor-grab place-items-center rounded-full bg-action text-action-foreground shadow-[var(--shadow-panel)] active:cursor-grabbing"
            label={t("comments")}
            onPointerDown={(event) => {
              if (event.button !== 0) return;
              event.preventDefault();
              event.stopPropagation();
              event.currentTarget.setPointerCapture(event.pointerId);
              draftCommentDrag.current = {
                pointerId: event.pointerId,
                startScreen: { x: event.clientX, y: event.clientY },
                origin: draftAnchor,
                moved: false,
              };
            }}
            onPointerMove={(event) => {
              const drag = draftCommentDrag.current;
              const instance = rf.current;
              if (!drag || drag.pointerId !== event.pointerId || !instance) return;
              if (!drag.moved && Math.hypot(event.clientX - drag.startScreen.x, event.clientY - drag.startScreen.y) <= 4) return;
              drag.moved = true;
              setDraftAnchor(moveCommentAnchorByScreenDelta(
                drag.origin,
                drag.startScreen,
                { x: event.clientX, y: event.clientY },
                (point) => instance.screenToFlowPosition(point),
              ));
            }}
            onPointerUp={(event) => {
              const drag = draftCommentDrag.current;
              if (!drag || drag.pointerId !== event.pointerId) return;
              draftCommentDrag.current = null;
              if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
            }}
            onPointerCancel={(event) => {
              const drag = draftCommentDrag.current;
              if (!drag || drag.pointerId !== event.pointerId) return;
              draftCommentDrag.current = null;
              setDraftAnchor(drag.origin);
            }}
          >
            <MessageSquare size={13} />
          </IconButton>
          <div className="-ml-3.5 -translate-y-3">
            <CommentComposer
              members={members}
              onCancel={() => setDraftAnchor(null)}
              onSubmit={async (draft) => {
                await onCreateComment?.(draftAnchor, draft);
                setDraftAnchor(null);
              }}
            />
          </div>
        </div>
      )}
    </ViewportPortal>
  );
}
