import React from "react";

import type { BoardFailureView, BoardItem } from "@/api/client";

/**
 * 画板上跑挂了的格子给人看的样子:后端出口的 `failures`(格子 id → 那一句、原文、原因和怎么修,按读的人的语言,见后端
 * domain/boards/failures)。格子里只存失败的原样;这几样另放一张表、由画板那一层放进来,格子、它的面板都从这里读 ——
 * 不进节点数据,也就不会随画布存回去。
 */
const BoardFailuresContext = React.createContext<Readonly<Record<string, BoardFailureView>>>({});

export function BoardFailuresProvider({ failures, children }: { failures?: Readonly<Record<string, BoardFailureView>>; children: React.ReactNode }) {
  return <BoardFailuresContext.Provider value={failures ?? {}}>{children}</BoardFailuresContext.Provider>;
}

/** 这一格失败展示要的几样(components/failure/FailureCard):那一句、原文、原因和怎么修、复制的那段。没跑挂就是 null。 */
export function useItemFailure(item: BoardItem) {
  const view = React.useContext(BoardFailuresContext)[item.id];
  if (item.run?.status !== "failed") return null;
  //: 出口的那一句没到(刚跑挂、画板还没重新拉)时用格子里存的原文 —— 至少说得出是什么
  const raw = (item.run.error ?? "").trim();
  return {
    summary: view?.error_summary?.trim() || raw,
    detail: view?.error_detail ?? null,
    fix: view?.error_hint ?? null,
    copyText: raw || view?.error_summary || "",
  };
}
