import type { QueryClient } from "@tanstack/react-query";

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
