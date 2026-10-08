import { useI18n } from "@/app/preferences";
import { atLeast } from "@/components/layout/workspaceMenu";

/**
 * 点不了的原因,两种长短:`reason` 是整句(说清他是「只读」、该找谁调),挂在按钮的悬停说明上;`brief` 是菜单条目底下
 * 那一行 —— 同一张菜单里每条写操作底下都有,整句重复四五遍会把菜单撑成三倍高。
 */
export type WriteBlock = { reason: string; brief: string };

/**
 * 这个人在这个工作区能不能改东西;不能的话为什么(体检 UM-20 / D62)。能写时是 `null`。
 *
 * 只读成员此前到处看得见「新建」「导入」「删除」,点了才收到一句 403。现在各页的写入口按角色收成灰的,说清
 * 他是「只读」、该找谁调 —— 按钮包一层 `<Hint disabledReason={blocked?.reason}>` 再 `disabled={Boolean(blocked)}`,
 * 菜单条目给 `disabledReason: blocked?.brief`(见 components/app/ActionMenu)。判据和后端同一条:写内容要「编辑」及以上
 * (backend domain/permissions)。**这只是不给不相干的人添乱,权限在后端** —— 每条写入接口各自把关。
 */
export function useWriteBlocked(role: string | null | undefined): WriteBlock | null {
  const t = useI18n();
  return atLeast(role, "editor") ? null : { reason: t("roleReadOnlyHint"), brief: t("roleReadOnlyBrief") };
}
