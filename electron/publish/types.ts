// 从桌面发布器移植的最小类型集。这里只保留 pageDriver/accountViews/adapters 用到的形状;
// 任务的持久化/状态源在 Open Studio 后端(/api/publish),publishWorker.ts 负责把后端任务映射成
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
// 高度一致,否则中间空档会露出 App 自己的顶栏,看着穿帮。
// 由 contracts/shared-constants.json 钉住(前端那份是 App.tsx 的 PUBLISH_BAR_HEIGHT)。
/**
 * 实时视图通道(IPC `browser:frame`)的线上格式。
 *
 * 两个 worker 共用一条通道和同一个前端面板——「自动化浏览器在干什么」对用户是一件事,不该因为
 * 内部分了 RPA 与发布两个执行器就冒出两个窗口。既然是同一份数据,类型也只能有一份:此前
 * browserWorker 与 publishWorker 各自声明了一个同形状的 interface,前端的全局声明是两者的并集,
 * 三处任何一处改了另外两处都不会报错。
 *
 * `dataUrl` 可选是本质约束而非偷懒:发布账号视图跑任务时不在窗口里,Chromium 不为未参与合成的
 * 视图产生像素(见 accountViews 的说明),此时只有 label 与 url。
 */
export interface LiveViewFrame {
  /** RPA 用会话 id,发布用账号 id。 */
  sessionId: string;
  /** 画面;取不到时缺省。 */
  dataUrl?: string;
  /** 当前步骤,如「B站 · 上传视频」。发布任务会带,RPA 会话不带。 */
  label?: string;
  url?: string;
  /** 已到终态(成功/失败)。面板据此停掉「运行中」的转圈,免得「失败」配着「后台运行中」自相矛盾。 */
  settled?: boolean;
}

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
