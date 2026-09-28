import type { MessageKey } from "@/app/messages";

/**
 * 工作区「重命名 / 删除」的门槛。
 *
 * 抽成函数是因为同一个动作有**两个入口**:设置 → 团队与成员里的那两个按钮,和切换器上
 * 每一行的按钮与右键菜单。门槛写两遍就会分叉,而分叉的表现是界面在两处对同一个人给出两种答案
 * —— 此前设置页就自己判权限、不查还剩几个,于是切换器灰掉的删除,在设置页照样点得下去。
 *
 * 判据本身:改名要 admin 及以上,删除只有 owner,且只剩一个工作区时谁都不许删(删到一个不剩,
 * 界面会落到没有工作区可选的状态)。角色认不出来时按**最低**权限处理:后端将来多一档角色,
 * 这里要么显眼地不给权限,要么就是悄悄把它当成了 owner,后者更糟。
 */
const RANK: Record<string, number> = { viewer: 0, editor: 1, admin: 2, owner: 3 };

/** 为什么点不了:`role` 是权限不够,`lastOne` 是只剩这一个。界面据此说原因、决定藏还是灰。 */
export type WorkspaceActionBlock = "role" | "lastOne" | null;

export interface WorkspaceMenuState {
  renameDisabled: boolean;
  deleteDisabled: boolean;
  renameBlockedBy: WorkspaceActionBlock;
  deleteBlockedBy: WorkspaceActionBlock;
}

export function workspaceMenuState(role: string | null | undefined, workspaceCount: number): WorkspaceMenuState {
  const rank = RANK[role ?? "viewer"] ?? -1;
  const renameBlockedBy: WorkspaceActionBlock = rank < RANK.admin ? "role" : null;
  const deleteBlockedBy: WorkspaceActionBlock = rank < RANK.owner ? "role" : workspaceCount < 2 ? "lastOne" : null;
  return {
    renameDisabled: renameBlockedBy !== null,
    deleteDisabled: deleteBlockedBy !== null,
    renameBlockedBy,
    deleteBlockedBy,
  };
}

/** 禁用原因的文案。没被拦就是 null —— 调用方拿它当 title,null 时退回动作名。 */
export function workspaceRenameBlockedReason(state: WorkspaceMenuState): MessageKey | null {
  return state.renameBlockedBy === "role" ? "workspaceRenameNeedsAdmin" : null;
}

export function workspaceDeleteBlockedReason(state: WorkspaceMenuState): MessageKey | null {
  if (state.deleteBlockedBy === "role") return "workspaceDeleteNeedsOwner";
  if (state.deleteBlockedBy === "lastOne") return "workspaceDeleteLastOne";
  return null;
}
