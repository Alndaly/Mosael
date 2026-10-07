/**
 * 笔记页,装上助手面板。
 *
 * 助手认识笔记(给消息挂笔记、把回复存成笔记),笔记再 import 助手就成了互相依赖(见 features/featureBoundaries.test)——
 * 所以笔记页只开一个口子(`AgentPanel`、`onNoteChange`),装配放在认识两边的这一侧。
 *
 * **笔记页说自己在哪**(ADR 0044):开着一篇就是那篇笔记,没开(或者那篇打不开)就是 AI Studio。在页面这一层登记 ——
 * 面板收起来时,免提浮标和智能体带你去也要知道你在哪篇笔记里。每一篇有自己的对话,换一篇就换成那一篇的。
 */

import React from "react";

import { useAgentPlace } from "@/features/agent/activePlace";
import { STUDIO_PLACE, type AgentPlace } from "@/features/agent/places";
import { NotesView, type NotesAgentPanelProps } from "@/features/notes/NotesView";
import type { Workspace } from "@/api/client";

//: 面板只在打开时才加载(NotesView 里那层 Suspense 接着它)。
const CanvasAgentChat = React.lazy(() => import("@/features/agent/CanvasAgentChat").then((m) => ({ default: m.CanvasAgentChat })));

function notePlace(noteId: string | null): AgentPlace {
  return noteId ? { kind: "note", id: noteId } : STUDIO_PLACE;
}

function NotesAgentPanel({ noteId, ...props }: NotesAgentPanelProps) {
  const place = React.useMemo(() => notePlace(noteId), [noteId]);
  return <CanvasAgentChat {...props} place={place} />;
}

export function NotesWithAgent({ workspace }: { workspace: Workspace }) {
  const [noteId, setNoteId] = React.useState<string | null>(null);
  useAgentPlace(notePlace(noteId));
  return <NotesView workspace={workspace} AgentPanel={NotesAgentPanel} onNoteChange={setNoteId} />;
}
