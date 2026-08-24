/**
 * 工作区右键菜单里「重命名 / 删除」的门槛。
 *
 * 抽成函数是因为同一个动作现在有**两个入口**:设置 → 团队与成员里的那两个按钮,和切换器上
 * 每一行的右键菜单。门槛写两遍就会分叉,而分叉的表现是界面在两处对同一个人给出两种答案。
 *
 * 判据本身:改名要 admin 及以上,删除只有 owner —— 与 features/settings/TeamSection 同源。
 * 角色认不出来时按**最低**权限处理:后端将来多一档角色,这里要么显眼地不给权限,要么就是
 * 悄悄把它当成了 owner,后者更糟。
 */
const RANK: Record<string, number> = { viewer: 0, editor: 1, admin: 2, owner: 3 };

export interface WorkspaceMenuState {
  renameDisabled: boolean;
  deleteDisabled: boolean;
}

export function workspaceMenuState(role: string | null | undefined, workspaceCount: number): WorkspaceMenuState {
  const rank = RANK[role ?? "viewer"] ?? -1;
  return {
    renameDisabled: rank < RANK.admin,
    // 只剩一个就不许删:设置页那个按钮永远作用在**当前**工作区上,删完还有 WorkspaceGate
    // 兜底;而这里能删任意一行,删到一个不剩的话,界面会落到没有工作区可选的状态。
    deleteDisabled: rank < RANK.owner || workspaceCount < 2,
  };
}
