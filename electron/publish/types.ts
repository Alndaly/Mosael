// 从桌面发布器移植的最小类型集。这里只保留 pageDriver/accountViews/adapters 用到的形状;
// 任务的持久化/状态源在 Open Studio 后端(/api/publish),worker.ts 负责把后端任务映射成
// 适配器期望的 PublishTask 形状。
import type { SupportedPlatform } from "./platforms";

export type Platform = SupportedPlatform;

export type TaskStatus =
  | "pending"
  | "running"
  | "prepared"
  | "waiting_manual"
  | "login_required"
  | "permission_required"
  | "blocked"
  | "cancelled"
  | "success"
  | "failed";

// 内嵌视图从顶部这么多像素处开始铺(上方留给「登录中·返回」条)。必须与 PublishViewBar 的
// 高度一致(h-12 = 48px),否则中间空档会露出 App 自己的顶栏,看着穿帮。
export const EMBED_HEADER_HEIGHT = 48;

export interface ViewState {
  visible: boolean;
  accountId: string | null;
  accountName: string | null;
  // 内嵌浏览器工具栏状态(仅可见视图有效):当前地址、前进/后退可用、加载中。
  url?: string;
  canGoBack?: boolean;
  canGoForward?: boolean;
  loading?: boolean;
}

/** 适配器消费的任务形状(与桌面版一致):videoPath / title / tags / platformOptions{dryRun,description,shortTitle}。 */
export interface PublishTask {
  id: string;
  accountId: string;
  accountName: string;
  platform: Platform;
  videoPath: string;
  title: string;
  tags: string[];
  platformOptions: Record<string, unknown>;
  scheduledAt: string | null;
  status: TaskStatus;
  errorMessage: string | null;
  screenshotPath: string | null;
  createdAt: string;
  updatedAt: string;
}
