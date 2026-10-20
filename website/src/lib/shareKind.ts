import type { CloudShareKind } from "@/lib/cloud";

/**
 * 分享类型的中文/英文名 —— **只有这一个地方判 kind**。
 *
 * 之前每处各自写 `kind === "board" ? 画布 : 工作流`,于是**插件被写成了"工作流"**
 * (维护者两次截图:详情页的 Blender MCP、控制台「我的分享」里的 TikHub / Text Toolkit)。
 * 两分支的写法天生会漏第三种 —— 现在集中到这一处,新增 kind 时只改这里。
 */
export type ShareKindCopy = { kindWorkflow: string; kindBoard: string; kindPlugin: string };

export function shareKindLabel(kind: CloudShareKind, copy: ShareKindCopy): string {
  if (kind === "board") return copy.kindBoard;
  if (kind === "plugin") return copy.kindPlugin;
  return copy.kindWorkflow;
}
