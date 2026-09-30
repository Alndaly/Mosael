import React from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { listConfirmations } from "@/api/client";
import { assetKeys, boardKeys, confirmationKeys } from "@/api/queryKeys";

/**
 * 一张确认卡批准或拒绝之后要刷新的缓存。卡背后的动作可能改了时间线、素材、工作流、生成任务、画板。
 *
 * 此前全局确认中心和对话里的内联卡各写一份清单:中心那份漏了工作流(在中心批准一次「改工作流」,
 * 工作流列表还是旧的),内联那份还失效了一个没有任何查询在用的键。两处批的是同一种卡,清单只该有一份。
 */
export function invalidateAfterDecision(qc: QueryClient, workspaceId: string): void {
  for (const queryKey of [
    confirmationKeys.all(workspaceId),
    ["sequences"],
    assetKeys.everywhere(),
    ["workflows"],
    ["generation-jobs"],
    //: 智能体改画板(edit_board)批准之后:打开着的那张板重取详情、合进本地,不必等下一次自己保存撞版本号。
    boardKeys.everywhere(),
  ]) {
    void qc.invalidateQueries({ queryKey });
  }
}

/** 看最近多少张执行完的卡。一次轮询之间落地的卡不会比这更多;多了也只是少刷一次,不会刷错。 */
const LANDED_WINDOW = 20;

/**
 * **不是这个界面批的卡**,执行落地之后这边也要刷新。
 *
 * `invalidateAfterDecision` 只挂在这个界面自己的「批准」按钮上,而卡还有别的批法:自动放行(「本会话始终允许」、
 * auto / bypass 档)在后端线程里批,飞书卡片在手机上批,另一台设备在它自己的界面里批。那些卡执行完了,这边
 * 没有任何一处知道 —— 用户反馈过:智能体删了两个素材,工具结果写着「2 个素材已删除」,素材库里两个都还在。
 * 库里确实删了(后端每个入口都提交,见 backend/tests/test_card_approval_lands),是素材库那份缓存没人让它过期:
 * 全局 staleTime 60 秒、不在获焦时重拉,开着的素材库页就一直是旧的。
 *
 * 所以这里不管是谁批的,只看「这个工作区里有没有新执行完的卡」:有,就按批完一张卡的清单刷一遍。挂在应用级,
 * 聊天面板收着、人在别的页面时同样生效。首次取到的那批不算 —— 那是打开应用之前就落地的,缓存本来就是新取的。
 */
export function useRefreshWhenCardsLand(workspaceId: string): void {
  const qc = useQueryClient();
  const landed = useQuery({
    queryKey: confirmationKeys.executed(workspaceId),
    queryFn: () => listConfirmations({ workspaceId, status: "executed", limit: LANDED_WINDOW }),
    refetchInterval: 3000,
    staleTime: 0,
  });
  // 按工作区记:切了工作区,另一个工作区的那批不是「新落地的」。
  const seen = React.useRef<{ workspaceId: string; ids: Set<string> } | null>(null);
  React.useEffect(() => {
    if (!landed.data) return;
    const ids = new Set(landed.data.map((card) => card.id));
    const before = seen.current?.workspaceId === workspaceId ? seen.current.ids : null;
    seen.current = { workspaceId, ids };
    if (before && [...ids].some((id) => !before.has(id))) invalidateAfterDecision(qc, workspaceId);
  }, [landed.data, qc, workspaceId]);
}
